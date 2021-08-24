import socket

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

def modeAP():
    """ Switch the device to wireless access point mode """
    pass

def modeClient(ssid, passkey):
    """ Switch the device to wireless client mode """
    pass