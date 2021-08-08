# Behavior Bracket
A neck-mounted device for risk-aware consentual kinky behavior management

## About
This project pairs a gyroscope and accelerometer with a Raspberry Pi Zero W and shock collar to provide an automated behavior control experience based on the motion of the wearer. The Raspberry Pi Zero runs a Flask/SocketIO web server which can be used to set the collar's mode and shock intensity, check its battery, and turn it off.

For now, the collar pairs with an E-Sky 998DR-1 shock collar to deliver the shock. This model is tricky to find these days, but similar models from other manufactuers are available. Beware however, as other collars may operate on a different frequency or protocol -- YMMV.

Once the case is finalized I'll upload the .stl file to this repo.

### Donate/Contact
If you like or use this project, please consider [donating](https://ko-fi.com/penelopede) so that I can keep working on this and other kinky engineering stuff!

If you build this project or fork it to make something cool, I'd love to hear about it! Hit me up on Mastodon [@deersyrup@yiff.life](https://yiff.life/@deersyrup)

### Future Plans
 1. Design and implement a TENS board to replace the E-Sky shock unit
    - Safer than the E-Sky unit (designed for use on humans)
    - Everything will fit in one package as opposed to being multiple devices
 2. Virtual Leash: Link the collar with a nearby Bluetooth device. If the device goes out of range, deliver a shock to the wearer
 3. Add some kind of settings/preferences menu for easy configuration via the web UI
 4. Detailed build instructions

## Modes
 - Pet Mode:
    - The wearer must remain on their hands and knees with their neck facing the ground
 - Statue Mode:
    - The wearer may not move
 - Sleep Deprivation Mode
    - Every 10 minutes, the wearer must move
    - CAUTION: Sleep deprivation can be extremely dangerous! Be careful and don't use this function for extended periods of time
 - Random Mode
    - Randomly shocks the wearer
 - Posture Mode
    - The wearer must remain standing completely upright

## Additional Features
 - Dock Lock
    - Punish the wearer if they attempt to disconnect the charging cable before the power level reaches 90%
    - You will be asked if you want to enable Dock Lock when you attach the charging cable to the device
    - While Dock Lock is turned on, you can tap the battery icon to turn it off
 - Power management
    - Low battery warning
    - Critical battery auto-shutdown

## Hardware
 - Raspberry Pi Zero W ($10)
 - BerryIMU v3 ($28)
    - SDA on board pin 27
    - SCL on board pin 28
 - WaveShare UPS HAT (C) ($24)
 - HiLetGo 3-01-0420-A (any cheap 433mHz transmitter should work) (~$5)
    - DATA on board pin 22
 - E-Sky 998DR-1 
    - These can be tricky to find; similar possibly compatable collars exist, but may operate on a different protocol or frequency. YMMV)
    - DO NOT use the shock function of this device on the wearer's neck -- I recommend the thigh
    - DO NOT lock this device to the wearer -- I haven't done enough testing yet to verify that the app won't crash in a weird and possibly dangerous way, so it's important to be able to remove the device quickly
 - (Optional) MicroUSB to magnetic charging cable adapter (~$15/3 pack)
 - (Optional) 3v Active Buzzer for audio feedback (>$1)

## Special Thanks
Shout-outs to the following folx for their help and ideas:
 - Friday Katte, for concepts and testing
 - Dahlia Bee, for naming the device

## Includes
This project incorporates code from the following repositories:
 - https://github.com/smouldery/shock-collar-control
 - https://github.com/ozzmaker/BerryIMU

## Disclaimer
This project provides software and instructions for the creation of a smart internet-enabled shock collar. I codemn in the strongest possible terms the use of shock collars on animals and unwilling humans.

This project uses comercially available products that are intended for use on non-humans and involve electricity. There is no guarantee of safe use, and you should be cleared by a medical professional first if you plan to use this device. 

This code is provided for demonstration and proof-of-concept purposes only. I am not responsible if you injure yourself or someone else with devices that aren't intended for use on humans.

Enjoy!