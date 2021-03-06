#!/usr/bin/python
#
#       This program includes a number of calculations to improve the
#       values returned from a BerryIMU. If this is new to you, it
#       may be worthwhile first to look at berryIMU-simple.py, which
#       has a much more simplified version of code which is easier
#       to read.
#
#
#       The BerryIMUv1, BerryIMUv2 and BerryIMUv3 are supported
#
#       This script is python 2.7 and 3 compatible
#
#       Feel free to do whatever you like with this code.
#       Distributed as-is; no warranty is given.
#
#       https://ozzmaker.com/berryimu/


import time
import math
import IMU
import datetime
import os
import sys


RAD_TO_DEG = 57.29578
M_PI = 3.14159265358979323846
G_GAIN = 0.070  # [deg/s/LSB]  If you change the dps for gyro, you need to update this value accordingly
AA =  0.40      # Complementary filter constant

MAG_LPF_FACTOR = 0.4    # Low pass filter constant magnetometer
ACC_LPF_FACTOR = 0.4    # Low pass filter constant for accelerometer
ACC_MEDIANTABLESIZE = 2         # Median filter table size for accelerometer. Higher = smoother but a longer delay
MAG_MEDIANTABLESIZE = 9         # Median filter table size for magnetometer. Higher = smoother but a longer delay

################# Compass Calibration values ############
# Use calibrateBerryIMU.py to get calibration values
# Calibrating the compass isnt mandatory, however a calibrated
# compass will result in a more accurate heading value.

magXmin =  0
magYmin =  0
magZmin =  0
magXmax =  0
magYmax =  0
magZmax =  0

'''
Here is an example:
magXmin =  -1748
magYmin =  -1025
magZmin =  -1876
magXmax =  959
magYmax =  1651
magZmax =  708
Dont use the above values, these are just an example.
'''
############### END Calibration offsets #################

#Kalman filter variables
Q_angle = 0.02
Q_gyro = 0.0015
R_angle = 0.005
y_bias = 0.0
x_bias = 0.0
z_bias = 0.0
XP_00 = 0.0
XP_01 = 0.0
XP_10 = 0.0
XP_11 = 0.0
YP_00 = 0.0
YP_01 = 0.0
YP_10 = 0.0
YP_11 = 0.0
ZP_00 = 0.0
ZP_01 = 0.0
ZP_10 = 0.0
ZP_11 = 0.0
KFangleX = 0.0
KFangleY = 0.0
KFangleZ = 0.0

def kalmanFilterY ( accAngle, gyroRate, DT):
    y=0.0
    S=0.0

    global KFangleY
    global Q_angle
    global Q_gyro
    global y_bias
    global YP_00
    global YP_01
    global YP_10
    global YP_11

    KFangleY = KFangleY + DT * (gyroRate - y_bias)

    YP_00 = YP_00 + ( - DT * (YP_10 + YP_01) + Q_angle * DT )
    YP_01 = YP_01 + ( - DT * YP_11 )
    YP_10 = YP_10 + ( - DT * YP_11 )
    YP_11 = YP_11 + ( + Q_gyro * DT )

    y = accAngle - KFangleY
    S = YP_00 + R_angle
    K_0 = YP_00 / S
    K_1 = YP_10 / S

    KFangleY = KFangleY + ( K_0 * y )
    y_bias = y_bias + ( K_1 * y )

    YP_00 = YP_00 - ( K_0 * YP_00 )
    YP_01 = YP_01 - ( K_0 * YP_01 )
    YP_10 = YP_10 - ( K_1 * YP_00 )
    YP_11 = YP_11 - ( K_1 * YP_01 )

    return KFangleY

def kalmanFilterX ( accAngle, gyroRate, DT):
    x=0.0
    S=0.0

    global KFangleX
    global Q_angle
    global Q_gyro
    global x_bias
    global XP_00
    global XP_01
    global XP_10
    global XP_11


    KFangleX = KFangleX + DT * (gyroRate - x_bias)

    XP_00 = XP_00 + ( - DT * (XP_10 + XP_01) + Q_angle * DT )
    XP_01 = XP_01 + ( - DT * XP_11 )
    XP_10 = XP_10 + ( - DT * XP_11 )
    XP_11 = XP_11 + ( + Q_gyro * DT )

    x = accAngle - KFangleX
    S = XP_00 + R_angle
    K_0 = XP_00 / S
    K_1 = XP_10 / S

    KFangleX = KFangleX + ( K_0 * x )
    x_bias = x_bias + ( K_1 * x )

    XP_00 = XP_00 - ( K_0 * XP_00 )
    XP_01 = XP_01 - ( K_0 * XP_01 )
    XP_10 = XP_10 - ( K_1 * XP_00 )
    XP_11 = XP_11 - ( K_1 * XP_01 )

    return KFangleX

def kalmanFilterZ ( accAngle, gyroRate, DT):
    Z=0.0
    S=0.0

    global KFangleZ
    global Q_angle
    global Q_gyro
    global z_bias
    global ZP_00
    global ZP_01
    global ZP_10
    global ZP_11


    KFangleZ = KFangleZ + DT * (gyroRate - z_bias)

    ZP_00 = ZP_00 + ( - DT * (ZP_10 + ZP_01) + Q_angle * DT )
    ZP_01 = ZP_01 + ( - DT * ZP_11 )
    ZP_10 = ZP_10 + ( - DT * ZP_11 )
    ZP_11 = ZP_11 + ( + Q_gyro * DT )

    z = accAngle - KFangleZ
    S = ZP_00 + R_angle
    K_0 = ZP_00 / S
    K_1 = ZP_10 / S

    KFangleZ = KFangleZ + ( K_0 * z )
    z_bias = z_bias + ( K_1 * z )

    ZP_00 = ZP_00 - ( K_0 * ZP_00 )
    ZP_01 = ZP_01 - ( K_0 * ZP_01 )
    ZP_10 = ZP_10 - ( K_1 * ZP_00 )
    ZP_11 = ZP_11 - ( K_1 * ZP_01 )

    return KFangleZ

def init():
    for i in range(0, 5):       # Try a couple times to detect IMU
        if(IMU.detectIMU()):    # Detect if BerryIMU is connected.
            break
        else:
            print(" No BerryIMU found!")
            continue

    IMU.initIMU()       #Initialise the accelerometer, gyroscope and compass

#Setup the tables for the mdeian filter. Fill them all with '1' so we dont get devide by zero error
acc_medianTable1X = [1] * ACC_MEDIANTABLESIZE
acc_medianTable1Y = [1] * ACC_MEDIANTABLESIZE
acc_medianTable1Z = [1] * ACC_MEDIANTABLESIZE
acc_medianTable2X = [1] * ACC_MEDIANTABLESIZE
acc_medianTable2Y = [1] * ACC_MEDIANTABLESIZE
acc_medianTable2Z = [1] * ACC_MEDIANTABLESIZE
mag_medianTable1X = [1] * MAG_MEDIANTABLESIZE
mag_medianTable1Y = [1] * MAG_MEDIANTABLESIZE
mag_medianTable1Z = [1] * MAG_MEDIANTABLESIZE
mag_medianTable2X = [1] * MAG_MEDIANTABLESIZE
mag_medianTable2Y = [1] * MAG_MEDIANTABLESIZE
mag_medianTable2Z = [1] * MAG_MEDIANTABLESIZE

# Set up time for first loop time calculation
a = datetime.datetime.now() 
def getValues(motionAlgorithm = 'accurate'):
    """
    motionAlgorithm determines whether to use complimentary filter or kalman filter to determine angles
        'fast'      = CF filter
        'accurate'  = Kalman filter
    """

    global acc_medianTable1X
    global acc_medianTable1Y
    global acc_medianTable1Z
    global acc_medianTable2X
    global acc_medianTable2Y
    global acc_medianTable2Z
    global mag_medianTable1X
    global mag_medianTable1Y
    global mag_medianTable1Z
    global mag_medianTable2X
    global mag_medianTable2Y
    global mag_medianTable2Z

    global a

    gyroXangle = 0.0
    gyroYangle = 0.0
    gyroZangle = 0.0
    angleX = 0.0
    angleY = 0.0
    angleZ = 0.0
    kalmanX = 0.0
    kalmanY = 0.0
    
    oldXMagRawValue = 0
    oldYMagRawValue = 0
    oldZMagRawValue = 0
    oldXAccRawValue = 0
    oldYAccRawValue = 0
    oldZAccRawValue = 0


    #Read the accelerometer,gyroscope and magnetometer values
    ACCx = IMU.readACCx()
    ACCy = IMU.readACCy()
    ACCz = IMU.readACCz()
    GYRx = IMU.readGYRx()
    GYRy = IMU.readGYRy()
    GYRz = IMU.readGYRz()
    MAGx = IMU.readMAGx()
    MAGy = IMU.readMAGy()
    MAGz = IMU.readMAGz()


    #Apply compass calibration
    MAGx -= (magXmin + magXmax) /2
    MAGy -= (magYmin + magYmax) /2
    MAGz -= (magZmin + magZmax) /2


    ##Calculate loop Period(LP). How long between Gyro Reads
    b = datetime.datetime.now() - a
    a = datetime.datetime.now()
    LP = b.microseconds/(1000000*1.0)
    # outputString = "Loop Time %5.2f " % ( LP )

    ###############################################
    #### Apply low pass filter ####
    ###############################################
    MAGx =  MAGx  * MAG_LPF_FACTOR + oldXMagRawValue*(1 - MAG_LPF_FACTOR);
    MAGy =  MAGy  * MAG_LPF_FACTOR + oldYMagRawValue*(1 - MAG_LPF_FACTOR);
    MAGz =  MAGz  * MAG_LPF_FACTOR + oldZMagRawValue*(1 - MAG_LPF_FACTOR);
    ACCx =  ACCx  * ACC_LPF_FACTOR + oldXAccRawValue*(1 - ACC_LPF_FACTOR);
    ACCy =  ACCy  * ACC_LPF_FACTOR + oldYAccRawValue*(1 - ACC_LPF_FACTOR);
    ACCz =  ACCz  * ACC_LPF_FACTOR + oldZAccRawValue*(1 - ACC_LPF_FACTOR);

    oldXMagRawValue = MAGx
    oldYMagRawValue = MAGy
    oldZMagRawValue = MAGz
    oldXAccRawValue = ACCx
    oldYAccRawValue = ACCy
    oldZAccRawValue = ACCz

    #########################################
    #### Median filter for accelerometer ####
    #########################################
    # cycle the table
    for x in range (ACC_MEDIANTABLESIZE-1,0,-1 ):
        acc_medianTable1X[x] = acc_medianTable1X[x-1]
        acc_medianTable1Y[x] = acc_medianTable1Y[x-1]
        acc_medianTable1Z[x] = acc_medianTable1Z[x-1]

    # Insert the lates values
    acc_medianTable1X[0] = ACCx
    acc_medianTable1Y[0] = ACCy
    acc_medianTable1Z[0] = ACCz

    # Copy the tables
    acc_medianTable2X = acc_medianTable1X[:]
    acc_medianTable2Y = acc_medianTable1Y[:]
    acc_medianTable2Z = acc_medianTable1Z[:]

    # Sort table 2
    acc_medianTable2X.sort()
    acc_medianTable2Y.sort()
    acc_medianTable2Z.sort()

    # The middle value is the value we are interested in
    ACCx = acc_medianTable2X[int(ACC_MEDIANTABLESIZE/2)];
    ACCy = acc_medianTable2Y[int(ACC_MEDIANTABLESIZE/2)];
    ACCz = acc_medianTable2Z[int(ACC_MEDIANTABLESIZE/2)];



    #########################################
    #### Median filter for magnetometer ####
    #########################################
    # cycle the table
    for x in range (MAG_MEDIANTABLESIZE-1,0,-1 ):
        mag_medianTable1X[x] = mag_medianTable1X[x-1]
        mag_medianTable1Y[x] = mag_medianTable1Y[x-1]
        mag_medianTable1Z[x] = mag_medianTable1Z[x-1]

    # Insert the latest values
    mag_medianTable1X[0] = MAGx
    mag_medianTable1Y[0] = MAGy
    mag_medianTable1Z[0] = MAGz

    # Copy the tables
    mag_medianTable2X = mag_medianTable1X[:]
    mag_medianTable2Y = mag_medianTable1Y[:]
    mag_medianTable2Z = mag_medianTable1Z[:]

    # Sort table 2
    mag_medianTable2X.sort()
    mag_medianTable2Y.sort()
    mag_medianTable2Z.sort()

    # The middle value is the value we are interested in
    MAGx = mag_medianTable2X[int(MAG_MEDIANTABLESIZE/2)];
    MAGy = mag_medianTable2Y[int(MAG_MEDIANTABLESIZE/2)];
    MAGz = mag_medianTable2Z[int(MAG_MEDIANTABLESIZE/2)];


    #Convert Gyro raw to degrees per second
    rate_gyr_x =  GYRx * G_GAIN
    rate_gyr_y =  GYRy * G_GAIN
    rate_gyr_z =  GYRz * G_GAIN


    #Calculate the angles from the gyro.
    gyroXangle+=rate_gyr_x*LP
    gyroYangle+=rate_gyr_y*LP
    gyroZangle+=rate_gyr_z*LP



    #Convert Accelerometer values to degrees
    AccXangle =  (math.atan2(ACCy,ACCz)+M_PI)*RAD_TO_DEG
    AccYangle =  (math.atan2(ACCz,ACCx)+M_PI)*RAD_TO_DEG
    AccZangle =  (math.atan2(ACCx,ACCy)+M_PI)*RAD_TO_DEG

    # Set values to 0,0 when device is upright
    AccYangle -= 180.0
    AccZangle -= 270.0

    if motionAlgorithm == 'fast':
        #Complementary filter used to combine the accelerometer and gyro values.
        angleX = AA*(angleX+rate_gyr_x*LP) +(1 - AA) * AccXangle
        angleY = AA*(angleY+rate_gyr_y*LP) +(1 - AA) * AccYangle
        angleZ = AA*(angleZ+rate_gyr_z*LP) +(1 - AA) * AccZangle

        # Map ranges from +/- 50 to +/- 90
        oldRange = 100
        newRange = 180

        angleX = (((angleX - (-50)) * newRange) / oldRange) + (-90)
        angleY = (((angleY - (-50)) * newRange) / oldRange) + (-90)
        angleZ = (((angleZ - (-50)) * newRange) / oldRange) + (-90)

    elif motionAlgorithm == 'accurate':
        #Kalman filter used to combine the accelerometer and gyro values.
        angleX = kalmanFilterY(AccYangle, rate_gyr_y,LP)
        angleY = kalmanFilterX(AccXangle, rate_gyr_x,LP)
        angleZ = kalmanFilterZ(AccZangle, rate_gyr_z,LP)

    #Calculate heading
    heading = 180 * math.atan2(MAGy,MAGx)/M_PI

    #Only have our heading between 0 and 360
    if heading < 0:
        heading += 360





    ####################################################################
    ###################Tilt compensated heading#########################
    ####################################################################
    #Normalize accelerometer raw values.
    accXnorm = ACCx/math.sqrt(ACCx * ACCx + ACCy * ACCy + ACCz * ACCz)
    accYnorm = ACCy/math.sqrt(ACCx * ACCx + ACCy * ACCy + ACCz * ACCz)


    #Calculate pitch and roll
    pitch = math.asin(accXnorm)
    try:
        roll = -math.asin(accYnorm/math.cos(pitch))
    except ValueError as e:
        roll = 0
        print("Roll Calculation Error")
        # If this fucks up disconnect and reconnect the ground wire on the IMU
        # TODO: maybe add a catch that reboots the collar? seems overkill, can we kill and revive the line or something?
        # I'm thinking a transistor on a gpio pin + 5v line going into berryimu? or is this dumb


    #Calculate the new tilt compensated values
    #The compass and accelerometer are orientated differently on the the BerryIMUv1, v2 and v3.
    #This needs to be taken into consideration when performing the calculations

    #X compensation
    magXcomp = MAGx*math.cos(pitch)+MAGz*math.sin(pitch)

    #Y compensation
    magYcomp = MAGx*math.sin(roll)*math.sin(pitch)+MAGy*math.cos(roll)-MAGz*math.sin(roll)*math.cos(pitch)


    #Calculate tilt compensated heading
    tiltCompensatedHeading = 180 * math.atan2(magYcomp,magXcomp)/M_PI

    if tiltCompensatedHeading < 0:
        tiltCompensatedHeading += 360


    ##################### END Tilt Compensation ########################


    # Package and return everything as a tidy dict
    return {
        'loopTime': LP,

        'motionAlgorithm': motionAlgorithm,

        'AccX': ACCx,
        'AccY': ACCy,
        'AccZ': ACCz,

        'AccXangle': AccXangle,
        'AccYangle': AccYangle,
        'AccZangle': AccZangle,

        'gyroXangle': gyroXangle,
        'gyroYangle': gyroYangle,
        'gyroZangle': gyroZangle,

        'angleX': angleX,
        'angleY': angleY,
        'angleZ': angleZ,

        'heading': heading,
        'tiltCompensatedHeading': tiltCompensatedHeading,
    }

    # #slow program down a bit, makes the output more readable
    # time.sleep(0.03)
