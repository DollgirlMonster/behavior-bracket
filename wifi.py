import os
import socket

sudo_mode = 'sudo '

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

def setWiFiMode(mode):
    """ 
    Enable or disable the wireless access point mode
    If enabled, disconnects the device from wifi and creates p2p hotspot for network config
    If disabled, sets the device up as wifi client with system network credentials
    Requires reboot, which must be handled by higher level function

    mode    string  ('host', 'client'), determines the WiFi mode we're switching into
    """
    # Determine what mode to switch to
    if mode == 'host': cmdVerb = 'enable'
    elif mode == 'client': cmdVerb = 'disable'

    # Enable/disable dnsmasq
    cmd = sudo_mode + f'systemctl {cmdVerb} dnsmasq'
    cmd_result = ""
    cmd_result = os.system(cmd)
    print(cmd + " - " + str(cmd_result))

    # Enable/disable hostapd
    cmd = sudo_mode + f'systemctl {cmdVerb} hostapd'
    cmd_result = os.system(cmd)
    print(cmd + " - " + str(cmd_result))

    # Copy appropriate dhcpcd config to system folder
    system_dhcpcd_conf_location = "/etc/dhcpcd.conf"

    if mode == 'host': dhcpcd_conf = './wifi-conf/dhcpcd/dhcpcd.host.conf'
    elif mode == 'client': dhcpcd_conf = './wifi-conf/dhcpcd/dhcpcd.client.conf'

    cmd = f'cp {dhcpcd_conf} {system_dhcpcd_conf_location}'
    cmd_result = os.system(cmd)
    print(cmd + " - " + str(cmd_result))

def getIPAddr(ifname='wlan0'):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.connect(('<broadcast>',0))
    ip = s.getsockname()[0]
    s.close()

    return ip

def clientConnect(ssid, passkey, client_country='US'):
    """ 
    Connect the device to a WiFi access point 
    Returns IP address
    """
    # write wifi config to wpa_supplicant.conf
    f = open('wpa_supplicant.conf', 'w')
    f.write(f'country={client_country}\n')
    f.write('ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\n')
    f.write('update_config=1\n')
    f.write('\n')
    f.write('network={\n')
    f.write(f'    ssid={ssid}\n')
    f.write(f'    psk={passkey}\n')
    f.write('}\n')
    f.close()

    # Move wpa_supplicant.conf to system folder
    system_wpa_supplicant_conf_location = "/etc/wpa_supplicant/wpa_supplicant.conf"

    cmd = 'mv wpa_supplicant.conf ' + system_wpa_supplicant_conf_location
    cmd_result = ""
    cmd_result = os.system(cmd)
    print(cmd + " - " + str(cmd_result))

    # restart wifi adapter
    print("Restarting wifi adapter...")
    print("Bringing down wlan0 interface...")
    cmd = sudo_mode + 'ifdown wlan0'
    cmd_result = os.system(cmd)
    print(cmd + " - " + str(cmd_result))

    time.sleep(2)

    print("Restarting wlan0 interface...")
    cmd = sudo_mode + 'ifup wlan0'
    cmd_result = os.system(cmd)
    print(cmd + " - " + str(cmd_result))

    time.sleep(10)

    print("Running iwconfig for wlan0...")
    cmd = 'iwconfig wlan0'
    cmd_result = os.system(cmd)
    print(cmd + " - " + str(cmd_result))

    print("Running ifconfig for wlan0...")
    cmd = 'ifconfig wlan0'
    cmd_result = os.system(cmd)
    print(cmd + " - " + str(cmd_result))

    ip_address = getIPAddr()

    return ip_address