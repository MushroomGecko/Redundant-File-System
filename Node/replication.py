from flask import Flask, render_template, request, send_file, session, redirect, abort
from flask_sock import Sock
import os
import shutil
import time
import threading
import subprocess
import atexit
import requests
from random import random
from typing import Union

MIN_SYNC_TIME = 10 # Length of time before a sync attempt will be allowed again after a successful sync with a particular server
SLEEP_TIME = 2 # Sync loop frequency (i.e. additional wait time before attempting syncs again). Lower number ensures sooner syncing if a sync failed previously.
SLEEP_TIME_RAND = 0.3 # Additional random amount added to prevent repeated concurrent sync timing conflicts
syncing_files = []
sync_data = {}

"""
Structure of data:
- .version file:
    user[ MERGE_CONFLICT]
    this.ip this.version
    [replica1.ip replica1.version]
    [...]
- version dict: Contains 'conflict' key if merge conflict exists. Other key:value pairs are IP:Version for each replica and this node.
- sync data: Contains key:value pairs of IP:Last Sync Time for each replica (not this node)
"""

thread_active = True
sync_thread = None

def create_replication_thread(ip_func, application):
    global getip
    global sync_thread

    getip = ip_func
    sync_thread = threading.Thread(target=trigger_sync)
    sync_thread.start()
    atexit.register(close_replication_thread)

def close_replication_thread():
    global thread_active
    global sync_thread
    thread_active = False
    sync_thread.join()

def overwrite_version(filepath: str, new_versions: dict):
    with open(filepath, 'r') as local_file:
        orig_lines = local_file.readlines()

    # Flag merge conflict if it exists
    if 'conflict' in new_versions:
        with open(os.path.dirname(filepath) + '/.conflict', 'w'):
            pass

    # Update versions. If any replicas changed, the sync thread will fix them on the next sync iteration.
    with open(filepath, 'w') as local_file:
        for line in enumerate(orig_lines):
            version_pair = line.split(' ')
            if len(version_pair) > 1:
                if version_pair[0] in new_versions:
                    version_pair[1] = new_versions[version_pair[0]]
            local_file.writeline(line)

def get_curr_version(filepath: str, return_primary: bool = False) -> dict:
    versions = {ip: 0 for ip in ([getip()] + list(sync_data.keys))}
    if not os.path.exists(filepath):
        return None
    else:
        if os.path.exists(os.path.dirname(filepath) + '/.conflict'):
            versions['conflict'] = True

        with open(filepath, 'r') as filereader:
            for i, line in enumerate(filereader):
                version_pair = line.split(' ')
                if i == 1 and return_primary:
                    versions['primary'] = version_pair[0]
                elif len(version_pair) > 1 and version_pair[0] in versions:
                    versions[version_pair[0]] = version_pair[1]

def send_version(ip: str, filepath: str):
    return requests.post('http://' + ip + ':25565/sync/version/' + filepath,
                         json=get_curr_version(filepath))

def recv_version(ip: str, filepath: str) -> dict:
    return requests.get('http://' + ip + ':25565/sync/version/' + filepath).json()

@app.route('/sync/version/<path:filepath>', methods=['GET', 'POST'])
def sync_version(filepath):
    if request.method == "POST":
        versions = request.get_json()
        overwrite_version(filepath, versions)
        return 'Success'
    else:
        data = {}
        if os.path.exists(os.path.dirname(filepath) + '/.conflict'):
            data['conflict'] = True

        with open(filepath, 'r') as local_file:
            for i, line in enumerate(local_file):
                if i <= 1:
                    continue

                version_pair = line.split(' ')
                data[version_pair[0]] = version_pair[1]
        return {'data': data}

def recv_sync_file(ip: str, filepath: str) -> requests.Response:
    return requests.get('http://' + ip + ':25565/sync/file/' + filepath)

def send_sync_file(ip: str, filepath: str, dst_filepath: str = None) -> requests.Response:
    if dst_filepath is None:
        dst_filepath = filepath

    with open(filepath, 'rb') as file:
        return requests.post('http://' + ip + ':25565/sync/file/' + dst_filepath,
                            files={'file':file})

@app.route('/sync/file/<path:filepath>', methods=['GET', 'POST'])
def sync_file(filepath):
    if request.method == "POST":
        file = request.files['file']
        with open(filepath, 'wb') as local_file:
            local_file.write(file.read())
        return 'Success'
    else:
        return send_file(filepath)

def attempt_sync_with(ip: str, filepath: str) -> bool:
    return requests.post('http://' + ip + ':25565/sync/lock/' + filepath, data=getip()).ok

def finish_sync_with(ip: str, filepath: str):
    requests.get('http://' + ip + ':25565/sync/lock/' + filepath)

@app.route('/sync/lock/<path:filepath>', methods=['GET', 'POST'])
def toggle_syncing_file(filepath):
    if request.method == "POST":
        # File is in quarantine (in the middle of a write)
        if os.path.exists(app.config['UPLOAD_FOLDER'] + '/' + os.path.basename(filepath)):
            abort(503)

        # File is already in the middle of a sync
        if filepath in syncing_files:
            abort(503)

        syncing_files.append(filepath)
        sync_data[request.get_data().decode()] = time.time()
        return 'Success'
    else:
        syncing_files.remove(filepath)

@app.route('/sync/ready', methods=['GET'])
def check_if_ready():
    return 'Success'

def trigger_sync():
    global thread_active
    thread_active = True
    # Wait until the app is active
    while not requests.get('http://' + getip() + ':25565/sync/ready').ok:
        time.sleep(1)

    while thread_active:
        # Update sync timing data
        with app.app_context():
            for ip in list(sync_data):
                if ip not in session['replicas']:
                    del sync_data[ip]
            for ip in session['replicas']:
                if ip not in sync_data:
                    sync_data[ip] = 0

        # Sync with the server that has not synced with for the longest time first
        sync_queue = sorted(sync_data, key=sync_data.get)
        
        for ip in sync_queue:
            if time.time() - sync_data[ip] < MIN_SYNC_TIME:
                continue

            for user in os.listdir('files/'):
                for file in os.listdir(user):
                    filepath = 'files/' + user + '/' + file + '/' + file
                    versionpath = 'files/' + user + '/' + file + '/.version'

                    # Get the current file version vector
                    orig_versions = get_curr_version(versionpath, True)
                    if orig_versions is None:
                        continue
                    primary = orig_versions['primary']
                    del orig_versions['primary']
                    local_versions = orig_versions.copy()

                    sync_versions(ip, filepath, versionpath, local_versions)

                    # Update version file if IPs or versions changed.
                    if any(orig_item[0] != new_item[0] or orig_item[1] != new_item[1]
                               for orig_item, new_item in zip(orig_versions.items(), local_versions.items())):
                        if 'conflict' in local_versions:
                            with open(os.path.dirname(versionpath) + '/.conflict', 'w'):
                                pass
                        elif os.path.exists(os.path.dirname(versionpath) + '/.conflict'):
                            os.remove(os.path.dirname(versionpath) + '/.conflict')

                        del local_versions['conflict']
                        with open(versionpath, 'w') as filewriter:
                            filewriter.writelines([user, primary])
                            filewriter.writelines([ip + ' ' + version for ip, version in local_versions.items()])

        time.sleep(SLEEP_TIME + random() * SLEEP_TIME_RAND)

def sync_versions(ip: str, filepath: str, versionpath: str, local_versions: dict) -> bool:
    """
    Syncs (replicates) a file with another node by comparing version vectors.
    If the one vector subsumes the other, the changes overwrite the file on the older node.
    Otherwise, a merge is attempted. If no conflicts arise
    """

    if filepath in syncing_files:
        return

    syncing_files.append(filepath)

    # if attempt sync succeeds, the other replica will update its syncing_files and sync_data
    if not attempt_sync_with(ip, filepath):
        syncing_files.remove(filepath)
        return False

    sync_data[ip] = time.time()

    remote_versions = recv_version(ip, versionpath)
    # If we're both in conflict, just do nothing
    if 'conflict' in local_versions and 'conflict' in remote_versions:
        syncing_files.remove(filepath)
        finish_sync_with(ip, filepath)
        return True
    
    # Create modified versions for easier comparisons
    local_compare = {local_ip:version for local_ip, version in local_versions.items() if local_ip != 'conflict' and local_ip in remote_versions}
    remote_compare = {local_ip:version for local_ip, version in remote_versions.items() if local_ip != 'conflict' and local_ip in local_versions}
    # If we match versions, do nothing
    if all(version == remote_compare[local_ip] for local_ip, version in local_compare.items()):
        pass
    # If the remote has higher versions than us across the board, we can safely copy remote
    elif all(version <= remote_compare[local_ip] for local_ip, version in local_compare.items()):
        response = recv_sync_file(ip, filepath)
        with open(filepath, 'wb') as file:
            file.write(response.content)
        overwrite_version(filepath, recv_version(ip, versionpath))
    # If we have higher versions than the remote across the board, remote can safely copy us
    elif all(version >= remote_compare[local_ip] for local_ip, version in local_compare.items()):
        send_version(ip, versionpath)
        send_sync_file(ip, filepath)
    # Version vectors conflict. Need to attempt merge
    else:
        conflict_file = recv_sync_file(ip, filepath)
        temp_path = os.path.dirname(filepath) + '/remote_' + os.path.basename(filepath)
        with open(temp_path, 'wb') as temp_file:
            temp_file.write(conflict_file.content)

        if not merge_files(filepath, temp_path):
            local_compare['conflict'] = True
        
        os.remove(temp_path)
        
        # Make the new vector the latest of the two vectors
        for ip in local_compare:
            local_versions[ip] = max(local_versions[ip], remote_versions[ip])

        send_version(ip, versionpath)
        send_sync_file(ip, filepath)

    syncing_files.remove(filepath)
    finish_sync_with(ip, filepath)
    return True

def merge_files(filepath1: str, filepath2: str, finalpath: Union[str, None] = None) -> bool:
    """
    Merges filepath1 and filepath2 onto finalpath.
    If any merge conflicts occur, the function returns false and does create a file.
    If finalpath is not specified, filepath1 is the target.

    @filepath1: The first file to use in the merge.
    @filepath2: The second file to use in the merge.
    @finalpath: The merged file to output to. If not specified, uses filepath1.
    """
    if finalpath is None:
        finalpath = filepath1

    CONFLICT_MSG = 'MERGE_CONFLICT'
    # Create a temp file to check if the merge has conflicts first
    temp_filepath = '"' + os.path.basename(filepath1) + os.path.basename(filepath2) + '"'
    with open(temp_filepath, 'w') as file:
        subprocess.run(['diff', '-D', CONFLICT_MSG, filepath1, filepath2], stdout=file)
    
    # Check the file for a merge conflict. Returns false if located, otherwise continues. Also removes the temp file.
    with open(temp_filepath, 'r') as temp_file:
        for line in temp_file:
            if line.startswith('#else /* ' + CONFLICT_MSG + ' */'):
                shutil.copy(temp_filepath, finalpath)
                os.remove(temp_filepath)
                return False
    os.remove(temp_filepath)

    # No merge conflicts. Merge the files together.
    with open(finalpath, 'w') as file:
        subprocess.run(['diff', '--line-format', '%L', filepath1, filepath2], stdout=file)
    return True