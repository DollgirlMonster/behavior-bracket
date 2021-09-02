import os
import socket

sudo_mode = 'sudo '

wpa_supplicant_conf =   "/etc/wpa_supplicant/wpa_supplicant.conf"
dhcpcd_conf =           "/etc/dhcpcd.conf"

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

def setAccessPointMode(enableAP):
    """ 
    Enable or disable the wireless access point mode
    If enabled, disconnects the device from wifi and creates p2p hotspot for network config
    If disabled, sets the device up as wifi client with system network credentials
    Requires reboot

    enableAP    bool    If true, set to access point. False, set to wifi client
    """
    # Set dnsmasq and hostapd
    if enableAP: cmdVerb = 'enable'
    else: cmdVerb = 'disable'

    cmd = sudo_mode + f'systemctl {cmdVerb} dnsmasq'
    cmd_result = ""
    cmd_result = os.system(cmd)
    print(cmd + " - " + str(cmd_result))

    cmd = sudo_mode + f'systemctl {cmdVerb} hostapd'
    cmd_result = os.system(cmd)
    print(cmd + " - " + str(cmd_result))

    # Set up dhcpcd config
    with open('dhcpcd.conf', 'w') as f:
        # These values are based on the default template from Raspbian
        f.write('hostname\n')   # Inform the DHCP server of our hostname for DDNS
        f.write('clientid\n')   # Use the hardware address of the interface for the Client ID
        f.write('persistent\n') # Persist interface configuration when dhcpcd exits
        f.write('option rapid_commit')  # Rapid commit support
        # A list of options to request from the DHCP server
        f.write('option domain_name_servers, domain_name, domain_search, host_name\n')
        f.write('option classless_static_routes\n')
        f.write('option interface_mtu\n')   # Respect the network MTU, applied to DHCP routes
        f.write('require dhcp_server_identifier\n') # A serverID is required by RFC2131
        f.write('slaac private\n')  # Generate stable private ipv6 address based from the DUID

        if enableAP:
            f.write('nohook wpa_supplicant\n')  # Without this line, entries in wpa_supplicant.conf will override the hotspot
            f.write('interface wlan0\n')
            f.write('static ip_address=192.168.50.10/24')
            f.write('routers=192.168.50.1')

    # Copy host mode dhcpcd config to system folder
    cmd = 'cp dhcpcd.conf ' + dhcpcd_conf
    cmd_result = os.system(cmd)
    print(cmd + " - " + str(cmd_result))

def getIPAddr(ifname='wlan0'):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.connect(('<broadcast>',0))
    ip = s.getsockname()[0]
    s.close()

    return ip

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
    print(cmd + " - " + str(cmd_result))

    # restart wifi adapter
    cmd = sudo_mode + 'ifdown wlan0'
    cmd_result = os.system(cmd)
    print(cmd + " - " + str(cmd_result))

    time.sleep(2)

    cmd = sudo_mode + 'ifup wlan0'
    cmd_result = os.system(cmd)
    print(cmd + " - " + str(cmd_result))

    time.sleep(10)

    cmd = 'iwconfig wlan0'
    cmd_result = os.system(cmd)
    print(cmd + " - " + str(cmd_result))

    cmd = 'ifconfig wlan0'
    cmd_result = os.system(cmd)
    print(cmd + " - " + str(cmd_result))

    ip_address = getIPAddr()

    return ip_address