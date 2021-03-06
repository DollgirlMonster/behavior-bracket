import requests
import json
import re
import os
import shutil
from hashlib import sha1
from pgpy import PGPKey, PGPMessage

downloadDir = './'

def getNewestVersionDetails(includePreReleases = True):
    """ Returns meta info about the latest release """
    if includePreReleases:
        repo = 'https://api.github.com/repos/DollgirlMonster/behavior-bracket/releases'
    else: 
        repo = 'https://api.github.com/repos/DollgirlMonster/behavior-bracket/releases/latest'

    response = requests.get(repo)
    response = json.loads(response.content)

    return {
        'name':         response[0]['name'],
        'version':      response[0]['tag_name'],
        'description':  response[0]['body'].replace('\r', ''),  # \r characters interfere with PGP validation
        'url':          response[0]['zipball_url'],
    }

def compareVersions(current, new):
    """
    Compares two version number strings
    @param current: first version string to compare
    @param new: second version string to compare
    @author <a href="http_stream://sebthom.de/136-comparing-version-numbers-in-jython-pytho/">Sebastian Thomschke</a>
    @return negative if current < new, zero if current == new, positive if current > new.
    """
    if current == new:
        # Don't even need to check because the version numbers are the same
        newerVersion = False
        return newerVersion

    # Get rid of text in the tag
    def num(s):
        if s.isdigit(): return int(s)
        return s

    seqA = list(map(num, re.findall('\d+|\w+', current.replace('alpha', ''))))
    seqB = list(map(num, re.findall('\d+|\w+', new.replace('alpha', ''))))

    # This is to ensure that 1.0 == 1.0.0
    lenA, lenB = len(seqA), len(seqB)
    for i in range(lenA, lenB): seqA += (0,)
    for i in range(lenB, lenA): seqB += (0,)

    # Compare version numbers
    newerVersion = False
    
    versionComparison = (seqA < seqB) - (seqA > seqB)

    if versionComparison in [-1, 0]: newerVersion = False
    elif versionComparison == 1: newerVersion = True

    return newerVersion

def hashZip(zipLocation=downloadDir + 'latest.zip'):
    """ Return the sha1 hash of the update zipfile """
    s = sha1()
    with open(zipLocation, "rb") as f:
        data = f.read() # read file in chunk and call update on each chunk if file is large.
        s.update(data)
        return s.hexdigest()

def verifyPGPSignature(message):
    """ 
    Verify PGPMessage() with our onboard public key 
    Returns:
    verification    bool    whether or not public key validates message
    updateHash      str     the sha1 hash included in the message
    """
    key, _ = PGPKey.from_file(downloadDir + 'updateConfirmation_publicKey.asc') # read public key from file

    message = PGPMessage.from_blob(message)                                     # Construct PGPMessage() from message

    verification = key.verify(message)                                          # Verify message with public key
    updateHash = message._message.decode()                                      # Decode message to get sha1 hash

    return verification, updateHash                                             # Return verification and sha1 hash

def downloadUpdate(updateURL):
    """ Download and uncompress update files """

    print("Downloading update package...")
    updatePackage = requests.get(updateURL)                     # Download update file

    print("Saving file...")
    with open(downloadDir + 'latest.zip', 'wb') as updateFile:  # Save update file
        updateFile.write(updatePackage.content)

def updateSoftware():
    """ Replace program files with those from the update file """
    
    print("Decompressing update...")
    shutil.unpack_archive(downloadDir + 'latest.zip', 'update', 'zip')          # Uncompress update file

    print("Copying update...")
    shutil.copytree(downloadDir + 'update', downloadDir + 'behavior-bracket')   # Copy update to program directory

    # Delete old .zip file
    print("Cleaning up...")
    os.remove(downloadDir + 'latest.zip')                                       # Delete update .zip file
    shutil.rmtree(downloadDir + 'update')                                       # Delete update directory