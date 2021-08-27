import requests
import json
from zipfile import ZipFile
import re
import os

dlFolder = './'

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
        'description':  response[0]['body'],
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

def downloadUpdate(updateURL):
    """ Download and uncompress update files """
    # Download update file
    print("Downloading update package...")
    updatePackage = requests.get(updateURL)

    # Save update file
    print("Saving file...")
    with open(dlFolder + 'latest.zip', 'wb') as updateFile:
        updateFile.write(updatePackage.content)

def updateSoftware():
    """ Replace program files with those from the update file """
    # Uncompress update
    print("Decompressing update...")
    with ZipFile(dlFolder + 'latest.zip', 'r') as zipObj:
        zipObj.extractall('behavior-bracket')

    # Delete old .zip file
    print("Cleaning up...")
    os.remove(dlFolder + 'latest.zip')

# Update procedure
# update = getNewestVersionDetails()

# print(compareVersions(__version__, update['version']))

# downloadUpdate(update['url'])
# updateSoftware()