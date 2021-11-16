# This code is an implementation of https://github.com/smouldery/shock-collar-control
# Major shout-out to its contributors and maintainers for making integration with this project a breeze

import pigpio
from time import sleep

gpio = pigpio.pi()          # Set up gpio

txKey = '00101100101001010' # Key to pair bracket and shock unit
radioDataPin = 25           # Board pin for radio DATA line
transmitting = False        # Keep track of whether or not we're sending data

def setup():
    """
    Initialize GPIO pin
    """
    gpio.set_mode(radioDataPin, pigpio.OUTPUT)      # Set up radio DATA pin as output
    gpio.wave_clear()                               # clear any existing waveforms


def transmit(self, waveID, txTime=1):
    """
    Transmit the radio signal in the background
    If we are already transmitting when this function is called, pass
    """
    if transmitting:        # If we're already transmitting a punishment
        pass                # Do nothing
    else:                   # Otherwise
        transmitting = True # Keep track of transmitting

        gpio.wave_send_repeat(waveID)   # transmit waveform
        sleep(txTime)                   # Sleep for txTime seconds
        gpio.wave_tx_stop()             # stop transmitting waveform
        gpio.write(radioDataPin, 0)     # Clear data from pin
        gpio.wave_clear()               # clear existing waveforms

        transmitting = False

def makeWaveform(self, sequence):
    """
    Create a waveform from our sequence of bytes
    """
    gpio.wave_clear()   # clear existing waveforms
    
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

    sequence_wave.append(pigpio.pulse(1<<radioDataPin, 0, start_bit))
    sequence_wave.append(pigpio.pulse(0, 1<<radioDataPin, start_delay))

    for x in range(0, 40): #adds the sequence bits to the waveform, in order.
        if int(sequence[x]) == 0:
            sequence_wave.append(pigpio.pulse(1<<radioDataPin, 0, zero_bit)) ## fix
            sequence_wave.append(pigpio.pulse(0, 1<<radioDataPin, zero_delay))
        else:
            sequence_wave.append(pigpio.pulse(1<<radioDataPin, 0, one_bit)) ## fix
            sequence_wave.append(pigpio.pulse(0, 1<<radioDataPin, one_delay))

    sequence_wave.append(pigpio.pulse(0, 0, EOS_delay))

    gpio.wave_add_generic(sequence_wave)    # Save the completed sequence
    waveID = gpio.wave_create()             # Create wave from sequence
    return waveID

def makeSequence(self, txMode, txPower, txChannel=1):
    """
    Create a bytestring to transmit to the shock unit using a given mode, power, and channel
    """
    # Need visibility of intensity so we know what power to set

    # Power 0-2 causes errors, so we just set to vibrate mode if power is low
    if int(txPower) < 3:    # If power is less than 3
        txPower = 30    # Set power to 30
        txMode = 3      # Set mode to vibrate
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