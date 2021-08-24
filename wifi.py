import os
import subprocess
import socket

wpa_supplicant_conf = "/etc/wpa_supplicant/wpa_supplicant.conf"
client_country = "US"  # TODO: optionify this

def isConnected():
    """ Returns True if connected to the Internet """
    try:
        sock = socket.create_connection(("1.1.1.1", 53))    # Attempt to connect
        if sock is not None:
            sock.close()                                    # Close the socket if it remains open
        return True
    except OSError:
        pass
    return False

def becomeAccessPoint():
    """ Switch the device to wireless access point mode """
    pass

def clientConnect(ssid, passkey):
    """ 
    Connect the device to a WiFi access point 
    Returns IP address
    """
    # write wifi config to file
    f = open('wifi.conf', 'w')
    f.write(f'country={client_country}\n')
    f.write('ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\n')
    f.write('update_config=1\n')
    f.write('\n')
    f.write('network={\n')
    f.write('    ssid="' + ssid + '"\n')
    f.write('    psk="' + passkey + '"\n')
    f.write('}\n')
    f.close()

    # Move wifi config to system folder
    cmd = 'mv wifi.conf ' + wpa_supplicant_conf
    cmd_result = ""
    cmd_result = os.system(cmd)
    print cmd + " - " + str(cmd_result)

    # restart wifi adapter
    cmd = sudo_mode + 'ifdown wlan0'
    cmd_result = os.system(cmd)
    print cmd + " - " + str(cmd_result)

    time.sleep(2)

    cmd = sudo_mode + 'ifup wlan0'
    cmd_result = os.system(cmd)
    print cmd + " - " + str(cmd_result)

    time.sleep(10)

    cmd = 'iwconfig wlan0'
    cmd_result = os.system(cmd)
    print cmd + " - " + str(cmd_result)

    cmd = 'ifconfig wlan0'
    cmd_result = os.system(cmd)
    print cmd + " - " + str(cmd_result)

    # Get IP address
    p = subprocess.Popen(['ifconfig', 'wlan0'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    out, err = p.communicate()

    ip_address = "<Not Set>"

    for l in out.split('\n'):
        if l.strip().startswith("inet addr:"):
            ip_address = l.strip().split(' ')[1].split(':')[1]

    return ip_address