import os
import subprocess
import random
import csv
from threading import Thread, Event, Timer
import time
import datetime
import statistics

from flask import Flask, request, abort, redirect, render_template  # Flask
from flask_socketio import SocketIO, emit                           # Flask-SocketIO

import imu
import battery
import buzzer
import radio as r
import wifi
import update

__version__ = '0.1-alpha.2'

# create and configure the Flask app
app = Flask(__name__, instance_relative_config=True)
app.config.from_mapping(
    SECRET_KEY='dev',
    DEBUG=True,
)

# Turn the flask app into a socketio app
socketio = SocketIO(app, async_mode=None, logger=True, engineio_logger=True, cors_allowed_origins="*")

# Set up multi threading
thread = Thread()
thread_stop_event = Event()

# Init global variables
punishmentRequests = {}     # Create empty container for punishment requests
requestPunishment = False   # [Obsolete] If not False, signal to punish and reason we are punishing TODO: delete
requestBeep = None          # If not None, what beep pattern to play

class EdgeDetector:
    """ Detects false/true transitions on an external signal"""
    def __init__(self, value=None):
        self.value = value          # Var to detect on
        self.edgeDetected = False   # Whether or not the value just changed
        # self.firstCheck = True      # Keep track of first time we test for edge detection

    def __str__(self):
        return str(self.value)

    def update(self, newValue):
        """ Update the stored value and return whether or not the value changed """
        # Compare the stored value against the new value,
        # and update edgeDetected bool accordingly
        if self.value != newValue:
            self.edgeDetected = True
        else: self.edgeDetected = False

        # if self.firstCheck: # First run return false
        #     self.firstCheck = False
        #     return False
        # else: return True

        self.value = newValue           # Replace stored value with new value

        return self.edgeDetected        # Return whether or not the value changed

class PunishmentTimer:
    """ 
    Defines a punishment with an associated warning and countdown 
    (seconds - 3)-second Pre-Timer -> 3s Warning Timer -> Shock
    """
    def __init__(self, seconds=5, punishmentSource='timer'):

        self.punishmentSource = punishmentSource    # Source of punishment passthrough for debug

        # We punish after n seconds, but at n-3 we sound a warning
        # This sets up for that
        if seconds > 3:
            self.seconds = seconds - 3
        else: self.seconds = 3                              # No timers shorter than 3 seconds

        # Set up threaded timer
        self.timer = Timer(self.seconds, self.doWarning)  # After (seconds - 3) seconds, play a warning sound -- 3 seconds later, punishment will occur
        self.timer.start()

    def doWarning(self):
        """ play warning sound, then wait 3 seconds and shock """
        # Need visibility of audio
        global requestBeep

        requestBeep = 'warning'
        self.timer = Timer(3, self.doPunishment)  # After 3 seconds, do punishment
        self.timer.start()

    def doPunishment(self):
        # Need visibility of audio and punishment
        global requestPunishment
        global requestBeep
        
        requestBeep = 'noncompliant'
        requestPunishment = self.punishmentSource

        # TODO: add bool to make punishment perpetual unless cancel() is called

    def cancel(self):
        self.timer.cancel()

class Sensor:
    """
    Defines and contains a sensor and its values
    """
    def __init__(self, name, updateFunction, sensorData, historyLength=20):
        """
        name            str     Human-readable name for the sensor to be displayed in the debug backend
        updateFunction  func    Function to call to update the sensor data: data are expected as a dict with keys matching sensorData
        sensorData      list    List of keys for recalling sensor data
        historyLength   int     Amount of historical data captures to store 
        history         list    last historyLength captures for sensorData
        """
        self.name = name
        self.updateFunction = updateFunction

        self.sensorData = {}    # Initialize sensor data dict
        for channel in sensorData: 
            self.sensorData[channel] = None  # Add sensor data keys to dict

        self.historyLength = historyLength
        self.history = []

    def read(self):
        newData = self.updateFunction()             # Get new data from the sensor
        for k in self.sensorData.keys():
            self.sensorData[k] = newData[k]         # Update sensor data in records
        
        socketio.emit(f"sensor_{self.name}", self.sensorData, namespace='/control') # Emit sensor data to server for debug

        self.history.append(self.sensorData)        # Add current sensor data to value history
        if len(self.history) > self.historyLength:  # If the number of values saved is over historyLength
            del self.history[0]                     # Delete the oldest value

        # Motion snapshot
        if app.config['moCap']:                                             # If motion logging enabled
            with open(f'{self.name}.csv', 'a', newline='') as file:         # Log motion
                writer = csv.DictWriter(file, list(self.sensorData.keys()))
                writer.writerow(self.sensorData)

# Init config
# TODO: Most globals will slowly be ported over to here as I get around to it
app.config.update(
    # INTERNET_CONNECTED = wifi.isConnected(),    # Whether or not we are connected to the internet
    INTERNET_CONNECTED = False,                 # TODO: remove -- temporarily testing without internet

    mode =              'off',                  # Operation mode for the device -- decides what logic is used for compliance determination
    safetyMode =        True,                   # If true, shocks will instead be delivered as vibrations
    warnBeforeShock =   False,                  # Whether to give a warning beep before punishing for noncompliance
    punishmentIntensity = 50,                   # Intensity of the shock -- if 3 or under, we will switch to vibrate mode
    moCap =             False,                  # Whether we should be logging motion data
    dockLock =          False,                  # Whether to enable Dock Lock (punish wearer if charger disconnected)
    startupChime =      True,                   # Whether to play a beep at launch to let the user know the device is ready to connect

    emitMotionData =    True,                   # Whether to send motion values to debug page
    motionAlgorithm =   'fast',                 # Algorithm used to calculate device rotation -- can be 'fast' or 'accurate'
)

# ooooooooooooo oooo                                           .o8           
# 8'   888   `8 `888                                          "888           
#      888       888 .oo.   oooo d8b  .ooooo.   .oooo.    .oooo888   .oooo.o 
#      888       888P"Y88b  `888""8P d88' `88b `P  )88b  d88' `888  d88(  "8 
#      888       888   888   888     888ooo888  .oP"888  888   888  `"Y88b.  
#      888       888   888   888     888    .o d8(  888  888   888  o.  )88b 
#     o888o     o888o o888o d888b    `Y8bod8P' `Y888""8o `Y8bod88P" 8""888P' 

# Thread: Radio communication
class radioThread(Thread):
    def __init__(self):
        self.safetyLimit = 10               # Number of punishment cycles until emergency auto-off

        self.radio = r.Radio()                   # Initialize radio

        super(radioThread, self).__init__()

    def waitLoop(self):
        global punishmentRequests                   # Get visibility of punishment requests container

        punishmentCycles = 0                        # Keep track of how many punishment transmissions we've sent
        while not thread_stop_event.isSet():
            # Punish if requested
            if True in punishmentRequests.values():         # If any punishment request channel is set to True
                if punishmentCycles < self.safetyLimit:     # If we're within safety limits
                    if app.config['safetyMode']:            # If safety mode is enabled
                        punishmentMode = 3                  # Set punishment mode to vibrate
                    else:                                   # Otherwise,
                        punishmentMode = 4                  # Set punishment mode to shock

                    sequence = self.radio.makeSequence(punishmentMode, app.config['punishmentIntensity'])   # Create punishment data sequence
                    waveID = self.radio.makeWaveform(sequence)  # Make waveform from data sequence
                    self.radio.transmit(waveID)                 # Transmit waveform

                punishmentCycles += 1                           # Increment punishment cycles
                socketio.emit('safetyPunishmentCycles', {       # Emit punishment cycles to web client
                    'punishmentCycles': punishmentCycles,
                }, namespace='/control')

                punishmentSource = [key for key,value in punishmentRequests.items() if value==True] # Find the source of the punishment request
                socketio.emit('compliance', {                                                       # Emit punishment info to web client
                    'compliance': False,
                    'punishmentSource': punishmentSource,
                }, namespace='/control')
            else:                                   # If there are no punishment requests
                punishmentCycles = 0                # Reset punishment cycles counter

                socketio.emit('compliance', {       # Emit compliance to web client
                    'compliance': True,
                    'punishmentSource': None,
                }, namespace='/control')
                
                # Stop the shock unit from going into sleep mode by periodically flashing the LED
                # We want to ping every two minutes on the first second
                # Unless we're already transmitting a punishment
                t = time.localtime()
                if t[4] % 2 == 0 and t[5] < 1:                  # Minutes are even and seconds are less than 1
                    KAsequence = self.makeSequence(txMode=1)    # Create flash sequence
                    KAwaveID = self.makeWaveform(KAsequence)    # Create flash wave
                    self.radio.transmit(KAwaveID, 0.5)          # Transmit flash

    def run(self):
        self.waitLoop()                                 # Begin loop

# Thread: Power management and battery
class pwrThread(Thread):
    def __init__(self):
        self.delay = 120
        self.pwrPin = 3   # GPIO pin for power switch

        self.charging = EdgeDetector(False) # Charging status with edge detection
        self.pwrSwitch = EdgeDetector(1)    # Power switch status with edge detection

        self.hasShownLowBatteryWarning = False  # Keep track of whether we've warned the user about low battery

        self.LOW_BATT_LEVEL = 20                                        # Battery percentage at which to warn the user that they should charge
        self.CRITICAL_BATT_LEVEL = 3                                    # Battery percentage at which to safely shut down the device to prevent damage
        self.PERCENT_MEAN_TABLE_SIZE = 100                              # Size of the mean table for the battery percentage
        self.battPercentHistory = [50] * self.PERCENT_MEAN_TABLE_SIZE   # List of previous percent values

        super(pwrThread, self).__init__()

    def battLoop(self):
        """
        Check the system battery level and broadcast to a socketio instance
        """
        # Need visiblity of global vars for communication
        global punishmentRequests
        global requestBeep

        while not thread_stop_event.isSet():
            battStat = battery.get_battery()

            # loadVoltage = battStat['loadVoltage']
            # power = battStat['power']
            current = battStat['current']
            percent = battStat['percent']

            # Cycle battery history
            for i in range(self.PERCENT_MEAN_TABLE_SIZE-1, 0, -1):
                self.battPercentHistory[i] = self.battPercentHistory[i - 1]

            self.battPercentHistory[0] = percent                        # Insert new battery history value
            avgBattPercent = statistics.mean(self.battPercentHistory)   # Get the mean of the battery percent history

            # Figure out whether we're charging to determine whether plugged status changed
            if current > 0: # Device is charging
                plugStatusChanged = self.charging.update(True)
                self.hasShownLowBatteryWarning = False  # Reset low battery warning
            else:           # Device is not charging
                plugStatusChanged = self.charging.update(False)

            # If the state just changed, do dock lock check
            if app.config['dockLock']:                      # If Dock Lock enabled
                if self.charging.value:                     # And unit is charging
                    punishmentRequests['dockLock'] = False  # No punishment
                    if plugStatusChanged:                   # And if unit just got plugged in
                        requestBeep = 'compliant'           # Play compliance beep
                else:                                       # Otherwise, if the unit is unplugged when it shouldn't be
                    punishmentRequests['dockLock'] = True   # Request punishment
                    if plugStatusChanged:                   # And if the unit just got unplugged
                        requestBeep = 'noncompliant'        # Play noncompliance beep
            else:
                punishmentRequests['dockLock'] = False      # If Dock Lock is off, cancel punishment
                
            # If fully charged, disable Dock Lock
            if avgBattPercent >= 99:
                app.config.update(dockLock = False)

            # If charge is under the low battery level, emit a warning to the user
            if avgBattPercent < self.LOW_BATT_LEVEL and self.charging.value == False:
                if not self.hasShownLowBatteryWarning:      # If we haven't shown the warning before
                    socket.emit('modal',
                    {
                        'title': "Low Battery",
                        'body': "Behavior Bracket's battery is running low. Charge the device soon, or it will shut down."
                    }, namespace='/control')                # Emit the warning
                    self.hasShownLowBatteryWarning = True   # Keep track of the fact that we've shown it

            # If charge is under the critical low battery level, shut down the device
            if avgBattPercent < self.CRITICAL_BATT_LEVEL:
                requestBeep = 'notify'
                socket.emit('modal',
                {
                    'title': "Critical Battery",
                    'body': "Behavior Bracket's battery has been depleted. The device is now shutting down."
                }, namespace='/control')
                os.system('sudo poweroff')

            # Broadcast to WebUI
            socketio.emit('battery', {
                'percent': avgBattPercent,
                'charging': self.charging.value,
                'dockLock': app.config['dockLock'],
            }, namespace='/control')

            time.sleep(0.25)

    def run(self):
        global punishmentRequests               # Get visibility of punishment request container
        punishmentRequests['dockLock'] = False  # Register dock lock channel

        self.battLoop()

# Thread: Audio Output thread
class beepThread(Thread):
    def __init__(self):
        buzzer.outputPinA = 33  # Define buzzer output pins
        buzzer.outputPinB = 40
        buzzer.setup()          # Set up buzzer pins
        
        super(beepThread, self).__init__()

    def waitLoop(self):
        # Need visibility of beep request var
        global requestBeep

        while not thread_stop_event.isSet():
            if requestBeep != None:
                buzzer.playSound(buzzer.sounds[requestBeep])    # Play requested sound over buzzer

                requestBeep = None

            time.sleep(self.delay)

    def run(self):
        self.waitLoop()

# Thread: Compliance update thread
class complianceThread(Thread):
    def __init__(self):
        berryimu.init() # Initialize IMU
        self.imu = Sensor(   # Set up IMU as Sensor
            name = 'IMU',
            updateFunction = berryimu.getValues(app.config['motionAlgorithm']),
            sensorData = [
                'accX',
                'accY',
                'accZ',
                'accXAngle',
                'accYAngle',
                'accZAngle',
                'gyroXAngle',
                'gyroYAngle',
                'gyroZAngle',
                'angleX',
                'angleY',
                'angleZ',
                'heading',
                'tiltCompensatedHeading',
            ],
        )

        self.mic = Sensor(   # Set up mic as sensor
            name = "Microphone",
            updateFunction = None,
            sensorData = [
                'audio',
                'level',
            ],
            historyLength = 10,
        )

        self.sensors = [self.imu, self.mic] # Bundle sensors in a list for convenient access

        self.stickyPunishment = False   # Bool to punish user "until something happens"

        # TODO: These would be better as some kind of Exercise() class
        self.wearerInRestPosition = EdgeDetector(True)      # Exercise mode: Keep track of whether the wearer is at rest
        self.repTimer = {                                   # Exercise mode: Timer for how long the wearer takes to do a rep
            'time': 0,
            'lastCheck': None
        }
        self.reps = 0                                       # Exercise mode: Reps counter for current exercise
        
        self.punishmentTimer = None             # Keep track of countdown to punishment, warning before punishment, etc.

        self.compliance = EdgeDetector(True)    # Bool to keep track of whether or not wearer is complying with the selected ruleset

        super(complianceThread, self).__init__()

    def angleTest(self, angle, lowBound, highBound):
        """
        Generalized function for angle-related compliance checks
        """
        forgiveness = 5     # +/- activation amounts on angles for debouncing and UX improvement

        # Adjust activation angles to account for forgiveness
        if self.compliance.value:           # If wearer is compliant
            lowBound -= forgiveness         # Widen the low and high bounds 
            highBound += forgiveness        # so that it's easier to stay within them
        else:                               # if wearer is noncompliant
            lowBound += forgiveness         # Tighten the low and high bounds
            highBound -= forgiveness        # so that it's harder to slip out once back in

        if highBound > angle > lowBound:    # If wearer is within a valid angle
            return True
        else: return False

    def getMotionDelta(self):
        """ Find change in recent movement """
        # Get the mean of the motion history values
        m = 0 
        for i in self.motionHistory:
            m += i['gyroXangle'] + i['gyroYangle'] + i['gyroZangle']
        m = m / len(self.motionHistory)

        # Find delta
        Mdelta = (self.motionHistory[-1]['gyroXangle'] + self.motionHistory[-1]['gyroYangle'] + self.motionHistory[-1]['gyroZangle']) - m

        # Send to the debug page
        socketio.emit('Mdelta', {
            'Mdelta': Mdelta,
        }, namespace='/control')

        return Mdelta

    def randomTest(self):
        """
        Random mode: randomly shocks the wearer
        """
        randomThreshold = 250   # Lower value = higher chance of shock

        if random.randint(1, randomThreshold) == 1:
            return False
        else:
            return True

    def petTest(self):
        """ 
        Pet Training Mode: wearer's neck must face down (Y rotation between -130 to -50) 
        """
        return self.angleTest(self.angleY, -130, -50)

    def freezeTest(self):
        """
        Freeze/Statue mode: user is not allowed to move
        """
        Mdelta = self.getMotionDelta()

        motionThreshold = 3    # Activation threshold

        # Check values against threshold
        if Mdelta > motionThreshold or Mdelta < - motionThreshold:
            return False
        else:
            return True

    def sleepDepTest(self):
        """
        Sleep deprivation mode: every 10 minutes, user is shocked until they move around -- probably shouldn't actually use this one but it's a cool idea right?
        """
        # Get the time -- if the minute field ends with a 0, we're in business
        t = time.localtime()
        if t[4] % 10 == 0:  # Minutes end with 0
            if t[5] < 1:    # Seconds less than 1
                self.stickyPunishment = True

        Mdelta = self.getMotionDelta()

        # Check values against threshold
        motionThreshold = 80
        if Mdelta > motionThreshold or Mdelta < - motionThreshold:  # user is moving
            self.stickyPunishment = False

        if self.stickyPunishment:
            return False
        else:
            return True

    def postureTest(self):
        """
        Posture mode: wearer must remain completely upright
        """
        postureThreshold = 7    # Activation threshold
        Ycalibration = -15      # Account for the angle of the device on the Y axis from its weight hanging from the collar

        if not self.angleTest(self.angleZ, -postureThreshold, postureThreshold) \
        or not self.angleTest(self.angleY, -postureThreshold + Ycalibration, postureThreshold + Ycalibration):
            return False    # Return false if either test returns false
        else:
            return True     # Otherwise, return true

    def fitnessTest(self):
        """
        Testing grounds for exercise detection: eventually I want to 
        spin this out into a whole range of features but for now 
        it's hidden on the main UI
        """
        global requestPunishment    # Get visibility of should transmit bool
        global requestBeep          # Get visibility of beep var

        # Check wearer's position
        if self.angleY < 20:                                            # Check Y rotation for situp detection
            positionJustChanged = self.wearerInRestPosition.update(False)
        else: positionJustChanged = self.wearerInRestPosition.update(True)

        if self.wearerInRestPosition.value: # If the wearer ir in rest position
            if positionJustChanged:         # and they just got into rest position
                self.resetRepTimer()        # reset the rep timer
                self.resetPunishmentTimer() # reset the punishment timer

        else:                               # Wearer is doing a rep
            if positionJustChanged:         # If their position just changed
                requestBeep = 'compliant'   # Request compliance beep
                self.reps += 1              # Increment rep counter
                self.resetRepTimer()        # Reset the rep timer
                self.resetPunishmentTimer() # Reset the punishment timer

        # Increment rep timer
        # TODO: Use this (in combination with gyroYangle for pushups?) to tell the wearer if they should do the exercise slower or faster
        now = datetime.datetime.now()
        if self.repTimer['lastCheck'] != None:
            self.repTimer['time'] += now - self.repTimer['lastCheck'] # repTimer += delta(now, then)
        else: 
            self.resetRepTimer()

        self.repTimer['lastCheck'] = now

        # Emit repTimer, reps to webUI
        socketio.emit('fitness', {
            'repTime':              self.repTimer['time'].second,
            'reps':                 self.reps,
            'wearerInRestPosition': self.wearerInRestPosition.value,
        }, namespace='/control')

    def resetRepTimer(self):
        """ Reset repTimer to 0 """
        today = datetime.datetime.today()   # Create empty datetime object for us to do time math on
        self.repTimer['time'] = datetime.datetime(today.year, today.month, today.day, 0, 0)

    def resetPunishmentTimer(self, delay=5):
        """ reset punishmentTimer to value set in delay """
        if self.punishmentTimer != None: self.punishmentTimer.cancel()              # Cancel current punishment timer if exists
        self.punishmentTimer = PunishmentTimer(delay, punishmentSource='fitness')   # Start punishment timer

    def testCompliance(self, motion):
        """
        Decide what test must be done based on the mode, and execute it
        """
        global punishmentRequests   # Get visibility of punishment requests
        global requestBeep          # Get visibility of beep queue

        if app.config['mode'] == 'off':         complianceJustChanged = self.compliance.update(True)
        elif app.config['mode'] == 'freeze':    complianceJustChanged = self.compliance.update(self.freezeTest())
        elif app.config['mode'] == 'pet':       complianceJustChanged = self.compliance.update(self.petTest())
        elif app.config['mode'] == 'sleepDep':  complianceJustChanged = self.compliance.update(self.sleepDepTest())
        elif app.config['mode'] == 'random':    complianceJustChanged = self.compliance.update(self.randomTest())
        elif app.config['mode'] == 'posture':   complianceJustChanged = self.compliance.update(self.postureTest())

        ### BEGIN Testing area for fitness mode
        elif app.config['mode'] == 'fitness':
            self.compliance.value = True
            self.fitnessTest()
        if app.config['mode'] != 'fitness': # TODO: Remove this when punishment timer is integrated with the rest of the motion thread
            if self.punishmentTimer != None: self.punishmentTimer.cancel()
            self.punishmentTimer = None
        ### END   Testing area for fitness mode

        # If compliance is true, do not request punishment
        if self.compliance.value:                       # If wearer is compliant
            punishmentRequests['interaction'] = False   # Set punishment request to False

            if complianceJustChanged:                   # And if they just started being compliant
                requestBeep = 'compliant'               # Request compliance beep
                
        else:                                           # If wearer is noncompliant
            punishmentRequests['interaction'] = True    # Set punishment request to True
            if complianceJustChanged:                   # And If they just started being noncompliant
                requestBeep = 'noncompliant'            # Request noncompliance beep


    def getMotion(self):
        """
        Fetch motion data from the IMU
        """
        while not thread_stop_event.isSet():
            for sensor in self.sensors:
                sensor.read()

            # Check for compliance
            self.testCompliance(motion)

    def run(self):
        global punishmentRequests                   # Get visibility of punishment requests
        punishmentRequests['interaction'] = False   # Register sensor channel in punishment requests

        self.getMotion()


# oooooo   oooooo     oooo            .o8       ooooo     ooo ooooo 
#  `888.    `888.     .8'            "888       `888'     `8' `888' 
#   `888.   .8888.   .8'    .ooooo.   888oooo.   888       8   888  
#    `888  .8'`888. .8'    d88' `88b  d88' `88b  888       8   888  
#     `888.8'  `888.8'     888ooo888  888   888  888       8   888  
#      `888'    `888'      888    .o  888   888  `88.    .8'   888  
#       `8'      `8'       `Y8bod8P'  `Y8bod8P'    `YbodP'    o888o 

# PAGES
# Debug page
@app.route('/debug', methods=["GET"])
def debug():
    return render_template(
        'debug.html',
        title = 'BBSS Debug',
        ipAddr = wifi.getIPAddr(),
    )

# Settings page
@app.route('/settings', methods=["GET"])
def settings():
    return render_template(
        'settings.html',
        title = 'Behavior Bracket Settings',
        version = __version__,
    )

# Main Page
@app.route('/', methods=["GET", "POST"])
def control():
    if app.config['INTERNET_CONNECTED']:    # If internet is connected
        return render_template(             # Return remote control page
            'control.html',
            title = 'Behavior Bracket',
        )
    else:                                   # Else return wifi setup page
        return render_template(
            'wifi-setup.html',
            title = 'Behavior Bracket Wi-Fi Setup',
            version = __version__,
        )

# INTERACTIONS
# Wi-Fi Connection Setup
@socketio.on('wifi-setup', namespace='/control')
def wifi_setup(msg):
    global requestBeep

    wifi.updateNetworkCredentials(msg['ssid'], msg['passkey'])  # Update wpa_supplicant with new credentials
    wifi.setWiFiMode('client')                                  # Set the device to WiFi client mode
    wifi.restartWiFiAdapter()                                   # Restart the WiFi adapter
    app.config['INTERNET_CONNECTED'] = wifi.isConnected()       # Check internet connection status
    if app.config['INTERNET_CONNECTED']:                        # If internet is connected
        requestBeep = 'slide'                                   # Play success sound
    else:                                                       # Else
        requestBeep = 'notify'                                  # Play error sound

# Motion Data Snapshot
@socketio.on('moCap', namespace='/control')
def mocap_toggle(msg):
    if msg['moCap']:
        app.config.update(moCap = True)     # Turn on motion capture
    else:
        app.config.update(moCap = False)    # Turn off motion capture

        # Set up the .csv file headers
        with open('motion.csv', 'a', newline='') as file:
            writer = csv.DictWriter(file, fieldnames = list(motion.keys()))
            writer.writeheader()

# On client connect
@socketio.on('connect', namespace='/control')
def test_connect():
    print('SocketIO Client connected')

# Mode selection
@socketio.on('mode', namespace='/control')
def mode_select(msg):
    app.config.update(mode = msg['mode'])   # Update mode setting with new value

# Intenstiy setting
@socketio.on('intensity', namespace='/control')
def intensity_select(msg):
    app.config.update(punishmentIntensity = msg['intensity'])   # Update punishment intensity setting with new value

# Dock Lock
@socketio.on('dockLock', namespace='/control')
def dock_lock(msg):
    app.config.update(dockLock = msg['enabled'])    # Update dock lock setting with new value

# Request for info update
@socketio.on('infoUpdate', namespace='/control')
def infoUpdate(msg):
    # Need visibility of global vars to display in UI
    global mode

    socketio.emit('infoUpdate', 
        {
            'mode':         app.config['mode'],
            'intensity':    app.config['punishmentIntensity'],
            'dockLock':     app.config['dockLock'],
        }, namespace='/control')

# Shut down request
@socketio.on('reboot', namespace='/control')
def reboot(msg):
    os.system('sudo reboot')

# Software update request
@socketio.on('softwareUpdate', namespace='/control')
def softwareUpdate(msg):
    metadata = update.getNewestVersionDetails()
    updateIsNewer = update.compareVersions(__version__, metadata['version'])    # Compare update version number against current version number

    if msg.command == 'getNewestVersionDetails':
        socket.emit('softwareUpdate',
            {
                'name':         metadata['name'],
                'version':      metadata['version'],
                'description':  metadata['description'],
                'url':          metadata['url'],
                
                'updateIsNewer': updateIsNewer,
            }, namespace='/control')

    elif msg.command == 'updateSoftware':
        if not updateIsNewer:                           # Verify that the update is a newer version than current
            socket.emit('modal',
            {
                'title': "System Update Error (0)",
                'body': "You're already on the latest version of Behavior Bracket's System Software."
            }, namespace='/control')
            return False

        signatureVerified, updateHash = update.verifyPGPSignature(metadata['description'])  # Check signature of update hash and retrieve the update hash

        if not signatureVerified:                       # Check that expected hash signature is verified
            # TODO: Check the date?
            socket.emit('modal',
            {
                'title': "System Update Error (1)",
                'body': "There was an error verifying the update information. Please try downloading the update again."
            }, namespace='/control')
            return False

        update.downloadUpdate(metadata['url'])          # Download the update

        zipHash = update.hashZip()                      # Hash the update zip file

        if zipHash != updateHash:                       # Check that update hash matches expected hash
            # Hashes do not match
            socket.emit('modal',
            {
                'title': "System Update Error (2)",
                'body': "There was an error verifying the update data. Please try downloading the update again."
            }, namespace='/control')
            return False

        update.updateSoftware()                         # Apply the update

        # Let user know we're done and restart
        socket.emit('spinner',
        {
            'body': "Rebooting...",
            'timer': 30
        }, namespace='/control')
        os.system('sudo reboot')

# Manual control
punishmentRequests['manual'] = False    # Register manual punishment channel
@socketio.on('manualControl', namespace='/control')
def manualControl(msg):
    # Need visibility of punishment and beep requests
    global punishmentRequests
    global requestBeep

    if msg['command'] == 'punish':
        requestBeep = 'noncompliant'
        punishmentRequests['manual'] = True     # Quickly toggle punishment on and off
        punishmentRequests['manual'] = False    # TODO: Test this
        
    elif msg['command'] =='warn':
        requestBeep = 'warning'

# ooo        ooooo            o8o              
# `88.       .888'            `"'              
#  888b     d'888   .oooo.   oooo  ooo. .oo.   
#  8 Y88. .P  888  `P  )88b  `888  `888P"Y88b  
#  8  `888'   888   .oP"888   888   888   888  
#  8    Y     888  d8(  888   888   888   888  
# o8o        o888o `Y888""8o o888o o888o o888o 
if __name__ == "__main__":
    print('Starting Power Management Thread')   # Start power management thread
    thread = pwrThread()
    thread.start()

    print('Starting Beep Thread')           # Start beep thread
    thread = beepThread()
    thread.start()

    print('Starting Radio Thread')          # Start radio thread
    thread = radioThread()
    thread.start()

    print('Starting Compliance Thread')     # Start main thread
    thread = complianceThread()
    thread.start()

    # Check wifi connection
    if app.config['INTERNET_CONNECTED']:    # If we're connected to the internet
        requestBeep = 'soliton'             # Play startup chime
    else:                                   # Otherwise,
        requestBeep = 'error'               # Play error beep
    
    app.run(debug=False, host='0.0.0.0')    # Start webserver 