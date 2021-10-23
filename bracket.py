import os
import subprocess
import random
import csv
from threading import Thread, Event, Timer
import time
import datetime
import statistics

from flask import Flask, request, abort, redirect, render_template  # Flask
from flask_socketio import SocketIO, emit                           # flask-socketio

import pigpio                                                       # pigpio
import berryimu
import battery
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
requestBeep = False         # If not False, what beep pattern to play
punishmentIntensity = 50    # Intensity of the shock -- if 3 or under, we will switch to vibrate mode

gpio = pigpio.pi()          # Set up gpio

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

# Init config
# TODO: Most globals will slowly be ported over to here as I get around to it
app.config.update(
    mode =              'off',                  # Operation mode for the device -- decides what logic is used for compliance determination
    safetyMode =        True,                   # If true, shocks will instead be delivered as vibrations
    warnBeforeShock =   False,                  # Whether to give a warning beep before punishing for noncompliance
    moCap =             False,                  # Whether we should log motion data
    dockLock =          False,                  # Whether to enable Dock Lock (punish wearer if charger disconnected)
    startupChime =      True,                   # Whether to play a beep at launch to let the user know the device is ready to connect

    emitMotionData =    True,                   # Whether to send motion values to debug page
    motionAlgorithm =   'fast',                 # Algorithm used to calculate device rotation -- can be 'fast' or 'accurate'

    networkConnected =  None,                   # Keep track of whether we're connected to the internet
)

# ooooooooooooo oooo                                           .o8           
# 8'   888   `8 `888                                          "888           
#      888       888 .oo.   oooo d8b  .ooooo.   .oooo.    .oooo888   .oooo.o 
#      888       888P"Y88b  `888""8P d88' `88b `P  )88b  d88' `888  d88(  "8 
#      888       888   888   888     888ooo888  .oP"888  888   888  `"Y88b.  
#      888       888   888   888     888    .o d8(  888  888   888  o.  )88b 
#     o888o     o888o o888o d888b    `Y8bod8P' `Y888""8o `Y8bod88P" 8""888P' 

# Thread: Radio communication
# This class is an implementation of https://github.com/smouldery/shock-collar-control
# Major shout-out to its contributors and maintainers for making integration with this project a breeze
class radioThread(Thread):
    def __init__(self):
        self.txKey = '00101100101001010'
        self.radioPin = 25  # Board pin 22

        self.transmitting = False
        self.safetyLimit = 10               # Number of punishment cycles until emergency auto-off

        super(radioThread, self).__init__()

    def transmit(self, waveID, txTime=1):
        """
        Transmit the radio signal in the background
        If we are already transmitting when this function is called, pass
        """
        if not self.transmitting:
            # Transmit punishment
            self.transmitting = True

            gpio.wave_send_repeat(waveID)  # transmit waveform
            time.sleep(txTime)
            gpio.wave_tx_stop()            # stop transmitting waveform
            gpio.write(self.radioPin, 0)
            gpio.wave_clear()              # clear existing waveforms

            self.transmitting = False
        else:
            # Transmitting already
            pass

    def makeWaveform(self, sequence):
        """
        Create a waveform from our sequence of bytes
        """
        gpio.wave_clear()                   # clear existing waveforms
        
        # create lists of parts of the wave we need 
        start_=[]
        one_=[]
        zero_=[]
        end_=[]
        sequence_wave=[]

        # define times
        start_bit = 1540
        start_delay = 800
        space = 1040
        zero_bit = 220
        zero_delay = space - zero_bit
        one_bit = 740
        one_delay = space - one_bit 
        EOS_delay = 7600

        sequence_wave.append(pigpio.pulse(1<<self.radioPin, 0, start_bit))
        sequence_wave.append(pigpio.pulse(0, 1<<self.radioPin, start_delay))

        for x in range(0, 40): #adds the sequence bits to the waveform, in order.
            if int(sequence[x]) == 0:
                sequence_wave.append(pigpio.pulse(1<<self.radioPin, 0, zero_bit)) ## fix
                sequence_wave.append(pigpio.pulse(0, 1<<self.radioPin, zero_delay))
            else:
                sequence_wave.append(pigpio.pulse(1<<self.radioPin, 0, one_bit)) ## fix
                sequence_wave.append(pigpio.pulse(0, 1<<self.radioPin, one_delay))

        sequence_wave.append(pigpio.pulse(0, 0, EOS_delay))

        gpio.wave_add_generic(sequence_wave)
        waveID = gpio.wave_create() 
        return waveID # save the completed wave and send wave ID to var

    def makeSequence(self, txMode=4, txChannel=1):
        """
        Create a bytestring to transmit to the shock unit using a given mode, power, and channel
        By default vibrates at 50 power for 1 second
        """
        # Need visibility of intensity so we know what power to set
        global punishmentIntensity
        
        txPower = punishmentIntensity

        # Power 0-2 causes errors, so we just set to vibrate mode if power is low
        if int(txPower) < 3:    # If power is less than 3
            txPower = 30    # Set power to 30
            txMode = 3      # Set mode to vibrate
        elif txMode is 1:   # Set power for LED flash
            txPower = 10

        # Check safety
        if app.config['safetyMode'] and txMode == 4:    # If we're about to shock and safety mode is on
            txMode = 3                                  # Vibrate instead

        # Set power
        # power_binary = '0000101'
        power_binary = '{0:07b}'.format(int(txPower))
        ## we convert the power value between 0-100 (After converting it to an interger) to a 7 bit binary encoded number. 

        # Set channel
        if txChannel == 2:
            channel_sequence = '111'
            channel_sequence_inverse = '000'
        else: 
            channel_sequence = '000'
            channel_sequence_inverse = '111'

        # Set mode
        if txMode == 1:
            # flash the ight on the collar. 
            mode_sequnce = '1000'
            mode_sequnce_inverse = '1110'
        elif txMode == 3:
            # vibrate the collar
            mode_sequnce = '0010'
            mode_sequnce_inverse = '1011'
        elif txMode == 4:
            # shock the collar 
            mode_sequnce = '0001'
            mode_sequnce_inverse = '0111'
        elif txMode == 2:
            # beep the collar
            mode_sequnce = '0100'
            mode_sequnce_inverse = '1101' 
        else:
            #mode = 2
            # beep the collar. it was done like this so the 'else' is a beep, not a shock for safety. 
            mode_sequnce = '0100'
            mode_sequnce_inverse = '1101' 

        # Set key
        key_sequence = self.txKey

        sequence = '1' + channel_sequence + mode_sequnce + key_sequence + power_binary + mode_sequnce_inverse + channel_sequence_inverse + '00'

        return sequence

    def run(self):
        global punishmentRequests                   # Get visibility of punishment requests container
        
        gpio.set_mode(self.radioPin, pigpio.OUTPUT) # Set up pin 22 as output
        gpio.wave_clear()                           # clear existing waveforms

        punishmentCycles = 0                        # Keep track of how many punishment transmissions we've sent
        while not thread_stop_event.isSet():
            # Punish if requested
            if True in punishmentRequests.values():
                if punishmentCycles < self.safetyLimit: # Only punish if we're within safety bounds
                    sequence = self.makeSequence()      # Create punishment data sequence
                    waveID = self.makeWaveform(sequence)# Make waveform from data sequence
                    self.transmit(waveID)               # Transmit waveform

                punishmentCycles += 1
                socketio.emit('safetyPunishmentCycles', {
                    'punishmentCycles': punishmentCycles,
                }, namespace='/control')

                punishmentSource = [key for key,value in punishmentRequests.items() if value==True] # Find the source of the punishment request
                socketio.emit('compliance', {
                    'compliance': False,
                    'punishmentSource': punishmentSource,
                }, namespace='/control')
            else:
                punishmentCycles = 0                # Reset punishment cycles counter

                socketio.emit('compliance', {
                    'compliance': True,
                    'punishmentSource': None,
                }, namespace='/control')
                
                # Stop the shock unit from going into sleep mode by periodically flashing the LED
                # We want to ping every two minutes on the first second
                # Unless we're already transmitting a punishment
                t = time.localtime()
                if t[4] % 2 == 0 and t[5] < 1:                  # Minutes are even and seconds are less than 1
                    KAsequence = self.makeSequence(txMode=1)    # Flash LED
                    KAwaveID = self.makeWaveform(KAsequence)
                    self.transmit(KAwaveID, 0.5)

# Thread: Power management and battery
class pwrThread(Thread):
    def __init__(self):
        self.delay = 120
        self.pwrPin = 3   # GPIO pin for power switch

        self.charging = EdgeDetector(False) # Charging status with edge detection
        self.pwrSwitch = EdgeDetector(1)    # Power switch status with edge detection

        self.CRITICAL_LOW_BATT_LEVEL = 3                                # Battery percentage at which to shut the device down to preserve battery health
        self.PERCENT_MEAN_TABLE_SIZE = 100                              # Size of the mean table for the battery percentage
        self.battPercentHistory = [50] * self.PERCENT_MEAN_TABLE_SIZE   # List of previous percent values

        super(pwrThread, self).__init__()

    def pwrSwitchCheck(self):
        """ 
        Query the power switch pin for state, on low edge send shutdown confirmation to webUI
        Pin is high on open, low on closed
        """
        pwrJustChanged = self.pwrSwitch.update(gpio.read(self.pwrPin))  # Query GPIO for power switch state
        if pwrJustChanged and self.pwrSwitch.value == 0:                # Low edge detected
            socketio.emit('shutdownConfirmation', {
                'foo': 'bar',
            }, namespace='/control')

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
            current = battStat['current']
            # power = battStat['power']
            percent = battStat['percent']

            # Cycle battery history
            for i in range(self.PERCENT_MEAN_TABLE_SIZE-1, 0, -1):
                self.battPercentHistory[i] = self.battPercentHistory[i - 1]

            # Insert new battery history value
            self.battPercentHistory[0] = percent

            # Get the mean of the battery percent history
            avgPercent = statistics.mean(self.battPercentHistory)

            # Figure out whether we're charging
            if current > 0:
                plugStatusChanged = self.charging.update(True)

            else:
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
                
            # If charge is over 99, disable Dock Lock
            if avgPercent >= 99:
                app.config.update(dockLock = False)

            # If charge is under the critical low battery level, shut down the device
            # A low battery warning is shown on the front-end at 5% battery -- this is handled clientside
            if avgPercent < self.CRITICAL_LOW_BATT_LEVEL:
                requestBeep = 'error'   # /should/ this beep though??
                os.system('sudo poweroff')

            # Broadcast to WebUI
            socketio.emit('battery', {
                'percent': avgPercent,
                'charging': self.charging.value,
                'dockLock': app.config['dockLock'],
            }, namespace='/control')

            time.sleep(0.25)

    def run(self):
        global punishmentRequests               # Get visibility of punishment request container
        punishmentRequests['dockLock'] = False  # Register dock lock channel

        # Set up gpio pin for communication with power switch
        gpio.set_mode(self.pwrPin, pigpio.INPUT)
        gpio.set_pull_up_down(self.pwrPin, pigpio.PUD_UP)

        self.battLoop()

# Thread: Beep thread
class beepThread(Thread):
    def __init__(self):
        self.buzzerPin =    13      # GPIO pin for buzzer

        self.chirpLength =  0.02    # Length of a short beep
        self.beepLength =   0.6     # Length of a long beep
        self.restLength =   0.08    # Length of rest between beeps
        self.delay =        0.1    # Length of time to wait between checking whether we should beep

        self.pattern = {
            'compliant':    ['chirp'],
            'noncompliant': ['chirp', 'chirp'],
            'warning':      ['beep'],
            'soliton':      ['chirp', 'beep'],
            'error':        ['beep', 'beep', 'beep'],
        }
        
        super(beepThread, self).__init__()

    def buzzerOn(self, onLength):
        gpio.write(self.buzzerPin, 1)
        time.sleep(onLength)
        gpio.write(self.buzzerPin, 0)

    def waitLoop(self):
        # Need visibility of beep request var
        global requestBeep

        while not thread_stop_event.isSet():
            if requestBeep != False:
                for i in self.pattern[requestBeep]:
                    if i == 'chirp': self.buzzerOn(self.chirpLength)
                    elif i == 'beep': self.buzzerOn(self.beepLength)

                    time.sleep(self.restLength)

                requestBeep = False

            time.sleep(self.delay)

    def run(self):
        self.waitLoop()

# Thread: Motion update thread
class motionThread(Thread):
    def __init__(self):
        berryimu.init()

        # Data vars so we can reference later
        self.AccX = 0
        self.AccY = 0
        self.AccZ = 0
        self.AccXAngle = 0
        self.AccYangle = 0
        self.AccZangle = 0
        self.gyroXangle = 0
        self.gyroYangle = 0
        self.gyroZangle = 0
        self.angleX = 0
        self.angleY = 0
        self.angleZ = 0
        # self.heading = 0
        # self.tiltCompensatedHeading = 0
        self.loopTime = 0

        self.motionHistory = []         # List of dicts with values AccX, AccY, AccZ, gyroXangle, gyroYangle, gyroZangle
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

        super(motionThread, self).__init__()

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

    def petTest(self):
        """ Pet Training Mode: wearer's neck must face down (Y rotation between -130 to -50) """
        return self.angleTest(self.angleY, -130, -50)

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
        if self.punishmentTimer != None: self.punishmentTimer.cancel()          # Cancel current punishment timer if exists
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
            motion = berryimu.getValues(app.config['motionAlgorithm'])

            # Update values
            self.AccX = motion['AccX']
            self.AccY = motion['AccX']
            self.AccZ = motion['AccX']
            self.AccXAngle = motion['AccXangle']
            self.AccYangle = motion['AccYangle']
            self.AccZangle = motion['AccZangle']
            self.gyroXangle = motion['gyroXangle']
            self.gyroYangle = motion['gyroYangle']
            self.gyroZangle = motion['gyroZangle']
            self.angleX = motion['angleX']
            self.angleY = motion['angleY']
            self.angleZ = motion['angleZ']
            # self.heading = motion['heading']
            # self.tiltCompensatedHeading = motion['tiltCompensatedHeading']
            self.loopTime = motion['loopTime']

            # Update web UI with motion data
            if app.config['emitMotionData']:
                socketio.emit('motion', {
                    'AccX': motion['AccX'], 
                    'AccY': motion['AccY'], 
                    'AccZ': motion['AccZ'], 

                    'AccXangle': motion['AccXangle'], 
                    'AccYangle': motion['AccYangle'],
                    'AccZangle': motion['AccZangle'],

                    'gyroXangle': motion['gyroXangle'],
                    'gyroYangle': motion['gyroYangle'],
                    'gyroZangle': motion['gyroZangle'],

                    'angleX': motion['angleX'],
                    'angleY': motion['angleY'],
                    'angleZ': motion['angleZ'],

                    # 'heading': motion['heading'],
                    # 'tiltCompensatedHeading': motion['tiltCompensatedHeading'],

                    'loopTime': motion['loopTime'],
                }, namespace='/control')

            # Update history with acceleration & rotation
            self.motionHistory.append({
                'AccX': motion['AccX'], 
                'AccY': motion['AccY'], 
                'AccZ': motion['AccZ'],
                'gyroXangle': motion['gyroXangle'],
                'gyroYangle': motion['gyroYangle'],
                'gyroZangle': motion['gyroZangle'],
            })
            if len(self.motionHistory) > 20:
                del self.motionHistory[0]

            # Motion snapshot
            if app.config['moCap']:                                             # If motion logging enabled
                with open('motion.csv', 'a', newline='') as file:               # Log motion
                    writer = csv.DictWriter(file, list(motion.keys()))
                    writer.writerow({
                        'loopTime': motion['loopTime'],
                        'motionAlgorithm': motion['motionAlgorithm'],

                        'AccX': motion['AccX'], 
                        'AccY': motion['AccY'], 
                        'AccZ': motion['AccZ'], 

                        'AccXangle': motion['AccXangle'], 
                        'AccYangle': motion['AccYangle'],
                        'AccZangle': motion['AccZangle'],

                        'gyroXangle': motion['gyroXangle'],
                        'gyroYangle': motion['gyroYangle'],
                        'gyroZangle': motion['gyroZangle'],

                        'angleX': motion['angleX'],
                        'angleY': motion['angleY'],
                        'angleZ': motion['angleZ'],

                        'heading': motion['heading'],
                        'tiltCompensatedHeading': motion['tiltCompensatedHeading'],
                    })

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

# Remote Control page
@app.route('/', methods=["GET"])
def control():
    return render_template(
        'control.html',
        title = 'Behavior Bracket',
    )

# INTERACTIONS
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
    app.config.update(mode = msg['mode'])

# Intenstiy setting
@socketio.on('intensity', namespace='/control')
def intensity_select(msg):
    global punishmentIntensity  # Need visibility of global intensity var

    punishmentIntensity = msg['intensity']

# Dock Lock
@socketio.on('dockLock', namespace='/control')
def dock_lock(msg):
    app.config.update(dockLock = msg['enabled'])

# Request for info update
@socketio.on('infoUpdate', namespace='/control')
def infoUpdate(msg):
    # Need visibility of global vars to display in UI
    global mode
    global punishmentIntensity

    socketio.emit('infoUpdate', 
        {
            'mode':         app.config['mode'],
            'intensity':    punishmentIntensity,
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

    if msg.command == 'getNewestVersionDetails':
        socket.emit('softwareUpdate',
            {
                'name':         metadata['name'],
                'version':      metadata['version'],
                'description':  metadata['description'],
                'url':          metadata['url'],
                
                'updateIsNewer': compareVersions(__version__, metadata['version'])
            }, namespace='/control')

    elif msg.command == 'updateSoftware':
        updateIsNewer = update.compareVersions(         # Compare update version number against current version number
            __version__, 
            metadata['version']
        )

        if not updateIsNewer:                           # Verify that the update is a newer version than current
            socket.emit('modal',
            {
                'title': "System Update Error (0)",
                'body': "You're already on the latest version of BBSS!"
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
    # Start power management & sound threads
    print('Starting Power Management Thread')
    thread = pwrThread()
    thread.start()

    print('Starting Beep Thread')
    thread = beepThread()
    thread.start()

    # Check wifi connection
    if not wifi.isConnected():
        # Start in access point mode
        app.config.update(networkConnected = False)
        requestBeep = 'error'   # Play error beep
        # wifi.setAccessPointMode(enableAP = True)  # TODO: uncomment once debugged
    else:
        # Start in client mode
        app.config.update(networkConnected = True)

        requestBeep = 'soliton' # Play startup chime

    # Start radio & motion threads
    print('Starting Radio Thread')
    thread = radioThread()
    thread.start()

    print('Starting Motion Thread')
    thread = motionThread()
    thread.start()
    
    # Start webserver 
    app.run(debug=False, host='0.0.0.0')