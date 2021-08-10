import os
import subprocess
import random
import csv
from threading import Thread, Event
from time import sleep, localtime

from flask import Flask, request, abort, redirect, render_template  # Flask
from flask_socketio import SocketIO, emit                           # flask-socketio

import pigpio                                                       # pigpio
import berryimu
import battery

# create and configure the Flask app
app = Flask(__name__, instance_relative_config=True)
app.config.from_mapping(
    SECRET_KEY='dev',
    DEBUG=False,
)

# Turn the flask app into a socketio app
socketio = SocketIO(app, async_mode=None, logger=True, engineio_logger=True, cors_allowed_origins="*")

# Set up multi threading
thread = Thread()
thread_stop_event = Event()

# Init global variables
mode = 'off'                # Operation mode for the collar -- determines what logic is used for compliance determination
requestPunishment = False   # Whether or not the collar should be transmitting the punish signal
requestBeep = 0             # Whether the collar should beep: 0 is no beeps, set number for number of beeps
punishmentIntensity = 50    # Intensity of the shock -- if 3 or under, we will switch to vibrate mode
enableDockLock = False      # Whether or not we should punish the wearer if the charger is disconnected

safetyMode = True           # Vibrate only -- change to False to enable shock

gpio = pigpio.pi()          # Set up gpio

class EdgeDetector:
    """ Detects false/true transitions on an external signal"""
    def __init__(self, value=None):
        self.value = value      # Bool to detect on
        self.last_value = None  # Initialize history
        self.firstCheck = True  # Keep track of first time we test for edge detection

    def edgeDetect(self):
        if self.value != self.last_value:
            self.last_value = self.value

            if self.firstCheck: # First run return false
                self.firstCheck = False
                return False
            else: return True

        else: 
            self.last_value = self.value
            return False

# Init config
# TODO: Most globals will slowly be ported over to here as I get around to it
app.config.update(
    moCap = False,  # Whether we should log motion data
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
            sleep(txTime)
            gpio.wave_tx_stop()            # stop transmitting waveform
            gpio.write(self.radioPin, 0)
            gpio.wave_clear     # clear existing waveforms

            self.transmitting = False
        else:
            # Transmitting already
            pass

    def makeWaveform(self, sequence):
        """
        Create a waveform from our sequence of bytes
        """
        gpio.wave_clear     # clear existing waveforms
        
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

    def makeSequence(self, txMode=3, txChannel=1):
        """
        Create a bytestring to transmit to the shock unit using a given mode, power, and channel
        By default vibrates at 50 power for 1 second
        """
        # Need visibility of intensity so we know what power to set, safetyMode to know if shock or vibrate
        global punishmentIntensity
        global safetyMode
        txPower = punishmentIntensity

        # Power 0-2 causes errors, so we just set to vibrate mode if power is low
        # something something experience design
        if int(txPower) < 3 and txMode is not 2:
            txPower = 30
            if safetyMode:  txMode = 3  # Vibrate
            else:           txMode = 4  # Shock
        elif txMode is 1:   # Set power for LED flash
            txPower = 10

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
        global requestPunishment                    # Get visibility of bool that determines whether we should transmit
        
        gpio.set_mode(self.radioPin, pigpio.OUTPUT) # Set up pin 22 as output
        gpio.wave_clear                             # clear existing waveforms

        while not thread_stop_event.isSet():
            # Punish if requested
            if requestPunishment:
                sequence = self.makeSequence()
                waveID = self.makeWaveform(sequence)
                self.transmit(waveID)

                requestPunishment = False
            else:
                # Stop the shock unit from going into sleep mode by periodically flashing the LED
                # We want to ping every two minutes on the first second
                # Unless we're already transmitting a punishment
                t = localtime()
                if t[4] % 2 == 0 and t[5] < 1:                  # Minutes are even and seconds are less than 1
                    KAsequence = self.makeSequence(txMode=1)    # Flash LED
                    KAwaveID = self.makeWaveform(KAsequence)
                    self.transmit(KAwaveID, 0.5)

# Thread: Power management and battery
class pwrThread(Thread):
    def __init__(self):
        self.delay = 120
        self.pwrPin = 3   # GPIO pin for power switch

        self.loadVoltage = 0
        self.current = 0
        self.power = 0
        self.percent = 0
        self.avgPercent = 0     # Stablized to prevent bouncing

        self.charging = EdgeDetector(False) # Charging status with edge detection
        self.pwrSwitch = EdgeDetector(1)    # Power switch status with edge detection

        self.battPercentHistory = []   # List of dicts with loadVoltage, current, power, percent

        super(pwrThread, self).__init__()

    def pwrSwitchCheck(self):
        """ 
        Query the power switch for state, on low edge send shutdown confirmation to webUI
        Pin is high on open, low on closed
        """
        self.pwrSwitch.value = gpio.read(self.pwrPin)
        if self.pwrSwitch.edgeDetect() and self.pwrSwitch.value == 0:   # Low edge detected
            socketio.emit('shutdownConfirmation', {
                'foo': 'bar',
            }, namespace='/test')

    def dockLockCheck(self):
        """ Returns false if the collar should be charging and is not """
        # Need visibility of enableDockLock
        global enableDockLock
        
        if self.charging.value:       # If the charger is connected, wearer is in the clear
            return True

        else: 
            return False      # If dockLock is on and charger is disconnected, punish

    def battLoop(self):
        """
        Check the system battery level and broadcast to a socketio instance
        """
        # Need visiblity of global vars for communication
        global enableDockLock
        global requestPunishment
        global requestBeep

        while not thread_stop_event.isSet():
            # Check power button and shut down if it's switched
            self.pwrSwitchCheck()

            battStat = battery.get_battery()

            self.loadVoltage = battStat['loadVoltage']
            self.current = battStat['current']
            self.power = battStat['power']
            self.percent = battStat['percent']

            # Update battery history
            self.battPercentHistory.append(self.percent)
            if len(self.battPercentHistory) > 100:
                del self.battPercentHistory[0]

            # Get the mean of the battery percent history
            self.avgPercent = sum(self.battPercentHistory) / len(self.battPercentHistory)

            # Figure out whether we're charging
            if self.current > 0:
                self.charging.value = True

            else:
                self.charging.value = False

            # If the state just changed, do dock lock check
            if enableDockLock:   # If Dock Lock enabled
                if self.dockLockCheck():    # User just plugged in and dock lock passed
                    if self.charging.edgeDetect():
                        requestBeep = 2
                else:                       # User is unplugged when they shouldn't be
                    requestPunishment = True
                    if self.charging.edgeDetect():
                        requestBeep = 1
                
            # If charge is over 90, disable Dock Lock
            # if self.percent >= 90:
            #     enableDockLock = False

            # Broadcast to WebUI
            socketio.emit('battery', {
                'percent': self.avgPercent,
                'charging': self.charging.value,
                'dockLock': enableDockLock,
            }, namespace='/test')

            sleep(0.25)

    def run(self):
        # Set up gpio pin for communication with power switch
        gpio.set_mode(self.pwrPin, pigpio.INPUT)
        gpio.set_pull_up_down(self.pwrPin, pigpio.PUD_UP)

        self.battLoop()

# Thread: Beep thread
class beepThread(Thread):
    def __init__(self):
        self.chirpLength = 0.02     # Length of a single beep
        self.delay = 0.08            # Length of time in between beeps, also length of time to wait between checking whether we should beep

        self.buzzerPin = 13         # GPIO pin for buzzer
        
        super(beepThread, self).__init__()

    def doBeep(self):
        gpio.write(self.buzzerPin, 1)
        sleep(self.chirpLength)
        gpio.write(self.buzzerPin, 0)

    def run(self):
        # Need visibility of global beep request int
        global requestBeep

        while not thread_stop_event.isSet():
            if requestBeep > 0:
                self.doBeep()
                requestBeep -= 1

            sleep(self.delay)

# Thread: Motion update thread
class motionThread(Thread):
    def __init__(self):
        self.delay = 0.03

        berryimu.init()

        # Data vars so we can reference later
        self.AccX = 0
        self.AccY = 0
        self.AccZ = 0
        # self.AccXAngle = 0
        # self.AccYangle = 0
        self.gyroXangle = 0
        self.gyroYangle = 0
        self.gyroZangle = 0
        self.CFangleX = 0
        self.CFangleY = 0
        # self.heading = 0
        # self.tiltCompensatedHeading = 0
        self.kalmanX = 0
        self.kalmanY = 0

        self.motionHistory = []         # List of dicts with values AccX, AccY, AccZ, kalmanX, kalmanY
        self.stickyPunishment = False   # Bool to punish user "until something happens"

        self.compliance = EdgeDetector(True)    # Bool to keep track of whether or not wearer is complying with the selected ruleset

        super(motionThread, self).__init__()

    def petTest(self):
        """
        pet training mode: user's neck must face down (Y rotation between -130 to -50)
        """
        if self.kalmanY > -130 and self.kalmanY < -50:
            return True
        else:
            return False

    def getMotionDelta(self):
        """
        Find change in recent movement
        """
        # Get the mean of the motion history values
        m = 0 
        for i in self.motionHistory:
            m += i['AccX'] + i['AccY'] + i['AccZ']
        m = m / len(self.motionHistory)

        # Find delta
        Mdelta = (self.motionHistory[-1]['AccX'] + self.motionHistory[-1]['AccY'] + self.motionHistory[-1]['AccZ']) - m

        # Send to the debug page
        # socketio.emit('Mdelta', {
        #     'Mdelta': Mdelta,
        # }, namespace='/test')

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

        # Check values against threshold
        motionThreshold = 50
        if Mdelta > motionThreshold or Mdelta < - motionThreshold:
            return False
        else:
            return True

    def sleepDepTest(self):
        """
        Sleep deprivation mode: every 10 minutes, user is shocked until they move around -- probably shouldn't actually use this one but it's a cool idea right?
        """
        # Get the time -- if the minute field ends with a 0, we're in business
        t = localtime()
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
        postureThreshold = 8

        if self.kalmanX < -postureThreshold or self.kalmanX > postureThreshold \
        or self.kalmanY < -postureThreshold or self.kalmanY > postureThreshold:
            return False
        else:
            return True

    def testCompliance(self, motion):
        """
        Decide what test must be done based on the mode, and execute it
        """
        global requestPunishment    # Get visibility of should transmit bool
        global requestBeep          # Get visibility of beep queue

        if mode == 'off':           self.compliance.value = True
        elif mode == 'freeze':      self.compliance.value = self.freezeTest()
        elif mode == 'pet':         self.compliance.value = self.petTest()
        elif mode == 'sleepDep':    self.compliance.value = self.sleepDepTest()
        elif mode == 'random':      self.compliance.value = self.randomTest()
        elif mode == 'posture':     self.compliance.value = self.postureTest()

        socketio.emit('compliance', {
            'compliance': self.compliance.value,
            'requestPunishment': requestPunishment,
        }, namespace='/test')

        # Decide whether we should beep based on change in compliance
        shouldBeep = False
        if self.compliance.edgeDetect():
            shouldBeep = True
    
        # If compliance is true, do not request punishment
        if self.compliance.value:
            if shouldBeep:
                requestBeep = 2
                
        else: 
            requestPunishment = True

            if shouldBeep:
                requestBeep = 1

    def getMotion(self):
        """
        Fetch motion data from the IMU
        """
        while not thread_stop_event.isSet():
            motion = berryimu.getValues()

            # Update values
            self.AccX = motion['AccX']
            self.AccY = motion['AccX']
            self.AccZ = motion['AccX']
            # self.AccXAngle = motion['AccXangle']
            # self.AccYangle = motion['AccYangle']
            self.gyroXangle = motion['gyroXangle']
            self.gyroYangle = motion['gyroYangle']
            self.gyroZangle = motion['gyroZangle']
            self.CFangleX = motion['CFangleX']
            self.CFangleY = motion['CFangleY']
            # self.heading = motion['heading']
            # self.tiltCompensatedHeading = motion['tiltCompensatedHeading']
            self.kalmanX = motion['kalmanX']
            self.kalmanY = motion['kalmanY']

            # Update web UI with motion data
            socketio.emit('motion', {
                'AccX': motion['AccX'], 
                'AccY': motion['AccY'], 
                'AccZ': motion['AccZ'], 

                # 'AccXangle': motion['AccXangle'], 
                # 'AccYangle': motion['AccYangle'],

                'gyroXangle': motion['gyroXangle'],
                'gyroYangle': motion['gyroYangle'],
                'gyroZangle': motion['gyroZangle'],

                'CFangleX': motion['CFangleX'],
                'CFangleY': motion['CFangleY'],

                # 'heading': motion['heading'],
                # 'tiltCompensatedHeading': motion['tiltCompensatedHeading'],

                'kalmanX': motion['kalmanX'],
                'kalmanY': motion['kalmanY'],
            }, namespace='/test')

            # Update history with acceleration & rotation
            self.motionHistory.append({
                'AccX': motion['AccX'], 
                'AccY': motion['AccY'], 
                'AccZ': motion['AccZ'], 
                'kalmanX': motion['kalmanX'],
                'kalmanY': motion['kalmanY'],
            })
            if len(self.motionHistory) > 20:
                del self.motionHistory[0]

            # Motion snapshot
            if app.config['moCap']:     # If motion logging enabled
                with open('motion.csv', 'a', newline='') as file:
                    writer = csv.DictWriter(file, fieldnames = motion.keys())
                    writer.writerow({
                        'AccX': motion['AccX'], 
                        'AccY': motion['AccY'], 
                        'AccZ': motion['AccZ'], 

                        'AccXangle': motion['AccXangle'], 
                        'AccYangle': motion['AccYangle'],

                        'gyroXangle': motion['gyroXangle'],
                        'gyroYangle': motion['gyroYangle'],
                        'gyroZangle': motion['gyroZangle'],

                        'CFangleX': motion['CFangleX'],
                        'CFangleY': motion['CFangleY'],

                        'heading': motion['heading'],
                        'tiltCompensatedHeading': motion['tiltCompensatedHeading'],

                        'kalmanX': motion['kalmanX'],
                        'kalmanY': motion['kalmanY'],
                    })

            # Check for compliance
            self.testCompliance(motion)
            
            sleep(self.delay)

    def run(self):
        self.getMotion()


# oooooo   oooooo     oooo            .o8       ooooo     ooo ooooo 
#  `888.    `888.     .8'            "888       `888'     `8' `888' 
#   `888.   .8888.   .8'    .ooooo.   888oooo.   888       8   888  
#    `888  .8'`888. .8'    d88' `88b  d88' `88b  888       8   888  
#     `888.8'  `888.8'     888ooo888  888   888  888       8   888  
#      `888'    `888'      888    .o  888   888  `88.    .8'   888  
#       `8'      `8'       `Y8bod8P'  `Y8bod8P'    `YbodP'    o888o 

# Debug page
@app.route('/debug', methods=["GET"])
def debug():
    return render_template(
        'debug.html',
        title = 'Smart Collar Debug',
    )

# Motion Data Snapshot
@socketio.on('moCap', namespace='/test')
def mocap_toggle(msg):
    if msg['moCap']:    app.config.update(moCap = True)
    else:               app.config.update(moCap = False)

@app.route('/', methods=["GET"])
def control():
    return render_template(
        'control.html',
        title = 'Smart Collar Control',
    )

# On client connect
@socketio.on('connect', namespace='/test')
def test_connect():
    print('SocketIO Client connected')

# Mode selection
@socketio.on('mode', namespace='/test')
def mode_select(msg):
    # Need visibility of global mode var
    global mode

    mode = msg['mode']

# Intenstiy setting
@socketio.on('intensity', namespace='/test')
def intensity_select(msg):
    # Need visibility of global intensity var
    global punishmentIntensity

    punishmentIntensity = msg['intensity']

# Dock Lock
@socketio.on('dockLock', namespace='/test')
def dock_lock(msg):
    # Need visibility of global dock lock var
    global enableDockLock

    enableDockLock = msg['enabled']

# Update request
@socketio.on('update', namespace='/test')
def update(msg):
    # Need visibility of global vars to display in UI
    global mode
    global punishmentIntensity
    global enableDockLock

    socketio.emit('update', 
        {
            'mode': mode,
            'intensity': punishmentIntensity,
            'dockLock': enableDockLock,
        }, namespace='/test')

# Shut down request
@socketio.on('pwrOff', namespace='/test')
def pwrOff(msg):
    os.system('sudo poweroff')

# Manual control
@socketio.on('manualControl', namespace='/test')
def manualControl(msg):
    # Need visibility of punishment and beep requests
    global requestPunishment
    global requestBeep

    if msg['command'] == 'punish':
        requestBeep = 3
        requestPunishment = True
        
    elif msg['command'] =='warn':
        requestBeep = 3

# Start threads only if they haven't been started before
if not thread.isAlive():
    print('Starting Power Management Thread')
    thread = pwrThread()
    thread.start()

    print('Starting Radio Thread')
    thread = radioThread()
    thread.start()

    print('Starting Beep Thread')
    thread = beepThread()
    thread.start()

    print('Starting Motion Thread')
    thread = motionThread()
    thread.start()

if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0')