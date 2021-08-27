#!/usr/bin/python
#
#   This file is for low-level communication with the IMU

import smbus
import time

bus = smbus.SMBus(0)

# Set values for communicating with the LIS3MDL
LIS3MDL_ADDRESS     = 0x1C

LIS3MDL_WHO_AM_I    = 0x0F

LIS3MDL_CTRL_REG1   = 0x20

LIS3MDL_CTRL_REG2   = 0x21
LIS3MDL_CTRL_REG3   = 0x22
LIS3MDL_CTRL_REG4   = 0x23
LIS3MDL_CTRL_REG5   = 0x24

LIS3MDL_STATUS_REG  = 0x27

LIS3MDL_OUT_X_L     = 0x28
LIS3MDL_OUT_X_H     = 0x29
LIS3MDL_OUT_Y_L     = 0x2A
LIS3MDL_OUT_Y_H     = 0x2B
LIS3MDL_OUT_Z_L     = 0x2C
LIS3MDL_OUT_Z_H     = 0x2D

LIS3MDL_TEMP_OUT_L  = 0x2E
LIS3MDL_TEMP_OUT_H  = 0x2F

LIS3MDL_INT_CFG     = 0x30
LIS3MDL_INT_SRC     = 0x31
LIS3MDL_INT_THS_L   = 0x32
LIS3MDL_INT_THS_H   = 0x33
 
# Set values for communicating with the LSM6DSL
LSM6DSL_ADDRESS          =  0x6A

LSM6DSL_WHO_AM_I         =  0x0F
LSM6DSL_RAM_ACCESS       =  0x01
LSM6DSL_CTRL1_XL         =  0x10
LSM6DSL_CTRL8_XL         =  0x17
LSM6DSL_CTRL2_G          =  0x11
LSM6DSL_CTRL10_C         =  0x19
LSM6DSL_TAP_CFG1         =  0x58
LSM6DSL_INT1_CTR         =  0x0D
LSM6DSL_CTRL3_C          =  0x12
LSM6DSL_CTRL4_C          =  0x13

LSM6DSL_STEP_COUNTER_L       =  0x4B
LSM6DSL_STEP_COUNTER_H       =  0x4C

LSM6DSL_OUTX_L_XL        =  0x28
LSM6DSL_OUTX_H_XL        =  0x29
LSM6DSL_OUTY_L_XL        =  0x2A
LSM6DSL_OUTY_H_XL        =  0x2B
LSM6DSL_OUTZ_L_XL        =  0x2C
LSM6DSL_OUTZ_H_XL        =  0x2D

LSM6DSL_OUT_L_TEMP       =  0x20
LSM6DSL_OUT_H_TEMP       =  0x21

LSM6DSL_OUTX_L_G         =  0x22
LSM6DSL_OUTX_H_G         =  0x23
LSM6DSL_OUTY_L_G         =  0x24
LSM6DSL_OUTY_H_G         =  0x25
LSM6DSL_OUTZ_L_G         =  0x26
LSM6DSL_OUTZ_H_G         =  0x27

LSM6DSL_TAP_CFG          =  0x58
LSM6DSL_WAKE_UP_SRC      =  0x1B
LSM6DSL_WAKE_UP_DUR      =  0x5C
LSM6DSL_FREE_FALL        =  0x5D
LSM6DSL_MD1_CFG          =  0x5E
LSM6DSL_MD2_CFG          =  0x5F
LSM6DSL_WAKE_UP_SRC      =  0x1B
LSM6DSL_TAP_THS_6D       =  0x59
LSM6DSL_INT_DUR2         =  0x5A
LSM6DSL_WAKE_UP_THS      =  0x5B
LSM6DSL_FUNC_SRC1        =  0x53

def detectIMU():
    #Detect which version of BerryIMU is connected using the 'who am i' register
    #BerryIMUv3 uses the LSM6DSL and LIS3MDL

    try:
        #Check for BerryIMUv3 (LSM6DSL and LIS3MDL)
        #If no LSM6DSL or LIS3MDL is connected, there will be an I2C bus error and the program will exit.
        #This section of code stops this from happening.
        LSM6DSL_WHO_AM_I_response = (bus.read_byte_data(LSM6DSL_ADDRESS, LSM6DSL_WHO_AM_I))
        LIS3MDL_WHO_AM_I_response = (bus.read_byte_data(LIS3MDL_ADDRESS, LIS3MDL_WHO_AM_I))

    except IOError as f:
        return False    # IMU detection failed
    else:
        if (LSM6DSL_WHO_AM_I_response == 0x6A) and (LIS3MDL_WHO_AM_I_response == 0x3D):
            print("Found BerryIMUv3 (LSM6DSL and LIS3MDL)")
            return True # IMU detection success

def writeByte(device_address,register,value):
    bus.write_byte_data(device_address, register, value)

# Set up memory for last values in case physical i2c connection is spotty
acc_x_l_last = 0
acc_x_h_last = 0
acc_y_l_last = 0
acc_y_h_last = 0
acc_z_l_last = 0
acc_z_h_last = 0

gyr_x_l_last = 0
gyr_x_h_last = 0
gyr_y_l_last = 0
gyr_y_h_last = 0
gyr_z_l_last = 0
gyr_z_h_last = 0

mag_x_l_last = 0
mag_x_h_last = 0
mag_y_l_last = 0
mag_y_h_last = 0
mag_z_l_last = 0
mag_z_h_last = 0

def readACCx():
    global acc_x_l_last
    global acc_x_h_last

    acc_l = 0
    acc_h = 0
    
    try:
        acc_l = bus.read_byte_data(LSM6DSL_ADDRESS, LSM6DSL_OUTX_L_XL)
        acc_h = bus.read_byte_data(LSM6DSL_ADDRESS, LSM6DSL_OUTX_H_XL)
        acc_x_l_last = acc_l
        acc_x_h_last = acc_h
    except IOError as e:
        acc_l = acc_x_l_last
        acc_h = acc_x_h_last

    acc_combined = (acc_l | acc_h <<8)
    return acc_combined  if acc_combined < 32768 else acc_combined - 65536


def readACCy():
    global acc_y_l_last
    global acc_y_h_last
    
    try:
        acc_l = bus.read_byte_data(LSM6DSL_ADDRESS, LSM6DSL_OUTY_L_XL)
        acc_h = bus.read_byte_data(LSM6DSL_ADDRESS, LSM6DSL_OUTY_H_XL)
        acc_y_l_last = acc_l
        acc_y_h_last = acc_h
    except IOError as e:
        acc_l = acc_y_l_last
        acc_h = acc_y_h_last

    acc_combined = (acc_l | acc_h <<8)
    return acc_combined  if acc_combined < 32768 else acc_combined - 65536


def readACCz():
    global acc_z_l_last
    global acc_z_h_last

    acc_l = 0
    acc_h = 0
    
    try:
        acc_l = bus.read_byte_data(LSM6DSL_ADDRESS, LSM6DSL_OUTZ_L_XL)
        acc_h = bus.read_byte_data(LSM6DSL_ADDRESS, LSM6DSL_OUTZ_H_XL)
        acc_z_l_last = acc_l
        acc_z_h_last = acc_h
    except IOError as e:
        acc_l = acc_z_l_last
        acc_h = acc_z_h_last

    acc_combined = (acc_l | acc_h <<8)
    return acc_combined  if acc_combined < 32768 else acc_combined - 65536


def readGYRx():
    global gyr_x_l_last
    global gyr_x_h_last

    gyr_l = 0
    gyr_h = 0
    
    try:
        gyr_l = bus.read_byte_data(LSM6DSL_ADDRESS, LSM6DSL_OUTX_L_G)
        gyr_h = bus.read_byte_data(LSM6DSL_ADDRESS, LSM6DSL_OUTX_H_G)
        gyr_x_l_last = gyr_l
        gyr_x_h_last = gyr_h
    except IOError as e:
        gyr_l = gyr_x_l_last
        gyr_h = gyr_x_h_last

    gyr_combined = (gyr_l | gyr_h <<8)
    return gyr_combined  if gyr_combined < 32768 else gyr_combined - 65536


def readGYRy():
    global gyr_y_l_last
    global gyr_y_h_last

    gyr_l = 0
    gyr_h = 0
    
    try:
        gyr_l = bus.read_byte_data(LSM6DSL_ADDRESS, LSM6DSL_OUTY_L_G)
        gyr_h = bus.read_byte_data(LSM6DSL_ADDRESS, LSM6DSL_OUTY_H_G)
        gyr_y_l_last = gyr_l
        gyr_y_h_last = gyr_h
    except IOError as e:
        gyr_l = gyr_y_l_last
        gyr_h = gyr_y_h_last

    gyr_combined = (gyr_l | gyr_h <<8)
    return gyr_combined  if gyr_combined < 32768 else gyr_combined - 65536


def readGYRz():
    global gyr_z_l_last
    global gyr_z_h_last

    gyr_l = 0
    gyr_h = 0
    
    try:
        gyr_l = bus.read_byte_data(LSM6DSL_ADDRESS, LSM6DSL_OUTZ_L_G)
        gyr_h = bus.read_byte_data(LSM6DSL_ADDRESS, LSM6DSL_OUTZ_H_G)
        gyr_z_l_last = gyr_l
        gyr_z_h_last = gyr_h
    except IOError as e:
        gyr_l = gyr_z_l_last
        gyr_h = gyr_z_h_last

    gyr_combined = (gyr_l | gyr_h <<8)
    return gyr_combined  if gyr_combined < 32768 else gyr_combined - 65536


def readMAGx():
    global mag_x_l_last
    global mag_x_h_last

    mag_l = 0
    mag_h = 0
    
    try:
        mag_l = bus.read_byte_data(LIS3MDL_ADDRESS, LIS3MDL_OUT_X_L)
        mag_h = bus.read_byte_data(LIS3MDL_ADDRESS, LIS3MDL_OUT_X_H)
        mag_l_last = mag_l
        mag_h_last = mag_h
    except IOError as e:
        mag_l = mag_x_l_last
        mah_h = mag_x_h_last

    mag_combined = (mag_l | mag_h <<8)
    return mag_combined  if mag_combined < 32768 else mag_combined - 65536


def readMAGy():
    global mag_y_l_last
    global mag_y_h_last

    mag_l = 0
    mag_h = 0
    
    try:
        mag_l = bus.read_byte_data(LIS3MDL_ADDRESS, LIS3MDL_OUT_Y_L)
        mag_h = bus.read_byte_data(LIS3MDL_ADDRESS, LIS3MDL_OUT_Y_H)
        mag_l_last = mag_l
        mag_h_last = mag_h
    except IOError as e:
        mag_l = mag_y_l_last
        mah_h = mag_y_h_last

    mag_combined = (mag_l | mag_h <<8)
    return mag_combined  if mag_combined < 32768 else mag_combined - 65536


def readMAGz():
    global mag_z_l_last
    global mag_z_h_last

    mag_l = 0
    mag_h = 0
    
    try:
        mag_l = bus.read_byte_data(LIS3MDL_ADDRESS, LIS3MDL_OUT_Z_L)
        mag_h = bus.read_byte_data(LIS3MDL_ADDRESS, LIS3MDL_OUT_Z_H)
        mag_z_l_last = mag_l
        mag_z_h_last = mag_h
    except IOError as e:
        mag_l = mag_z_l_last
        mah_h = mag_z_h_last

    mag_combined = (mag_l | mag_h <<8)
    return mag_combined  if mag_combined < 32768 else mag_combined - 65536


def initIMU():
    # 10 tries to connect
    # TODO: Handle failure to connect
    for i in range(10):
        try: 
            #initialise the accelerometer
            writeByte(LSM6DSL_ADDRESS,LSM6DSL_CTRL1_XL,0b10011111)           #ODR 3.33 kHz, +/- 8g , BW = 400hz
            writeByte(LSM6DSL_ADDRESS,LSM6DSL_CTRL8_XL,0b11001000)           #Low pass filter enabled, BW9, composite filter
            writeByte(LSM6DSL_ADDRESS,LSM6DSL_CTRL3_C,0b01000100)            #Enable Block Data update, increment during multi byte read

            #initialise the gyroscope
            writeByte(LSM6DSL_ADDRESS,LSM6DSL_CTRL2_G,0b10011100)            #ODR 3.3 kHz, 2000 dps

            #initialise the magnetometer
            writeByte(LIS3MDL_ADDRESS,LIS3MDL_CTRL_REG1, 0b11011100)         # Temp sesnor enabled, High performance, ODR 80 Hz, FAST ODR disabled and Selft test disabled.
            writeByte(LIS3MDL_ADDRESS,LIS3MDL_CTRL_REG2, 0b00100000)         # +/- 8 gauss
            writeByte(LIS3MDL_ADDRESS,LIS3MDL_CTRL_REG3, 0b00000000)         # Continuous-conversion mode
        except IOError as e:
            time.sleep(0.1)  # Try and give her a sec to right herself
            continue
        break