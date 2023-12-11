from flask import Flask, render_template, request, send_file, session, redirect
from flask_sock import Sock
import os
import subprocess
import socket
import json
from werkzeug.utils import secure_filename
import requests

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "quarantine/"
app.config['SECRET_KEY'] = "Your_secret_string"
app.config['SOCK_SERVER_OPTIONS'] = {'ping_interval': 25}
sock = Sock(app)

# List of active users
users = []
# IP of the master server
master = "192.168.1.2"

# Self explainitory. Server gets the IP of itself
def getip():
    ip = os.popen("ip a").read().split('\n')
    for i in ip:
        i = i.strip()
        if "inet" in i:
            if "127.0.0.1" in i or "::" in i:
                continue
            else:
                return i.split(" ")[1].split("/")[0]
    return 0


@app.route('/', methods=['GET', 'POST'])
def index():
    # Preemptively gets information about a user about to be redirected
    if request.method == 'POST':
        user_data = request.json
        for i in users:
            if i['username'] == user_data[0]['username'] or i['ip'] == user_data[0]['ip']:
                print("here")
                users.remove(i)
                break
        users.append(user_data[0])
        print(users)
        return render_template('index.html')

    # If the user already has a session stored for this node, redirect to the file page
    if 'ip' in session and 'username' in session:
        return redirect('/files')

    for i in users:
        # Establish user's session cookies
        if str(request.remote_addr) == i['ip']:
            session['ip'] = i['ip']
            session['replicas'] = i['replicas']
            session['username'] = i['username']
            print(session['ip'], session['replicas'], session['username'])
            return redirect('/files')
    # If user does not have a session in this node, redirect back to master.
    return redirect('http://' + master + ':25565')

def gen_version_string():
    base_list = [session['username'], getip(), getip() + ' 1']
    for replica in session['replicas']:
        base_list.append(replica + ' 0')
    return "\n".join(base_list)

@app.route('/files', methods=['GET', 'POST'])
def files_index():
    public_files = 'files/' + session['username'] + '/'

    if session['username'] not in os.listdir('files/'):
        os.system('mkdir ' + public_files)
        for i in session['replicas']:
            if i != getip():
                os.system('sshpass -p 12345 ssh ' + "cmsc621@" + i + ' mkdir /home/cmsc621/Desktop/' + public_files)

    print(session['ip'], session['username'], session['replicas'])
    if request.method == "POST":

        filesdown = request.form.getlist('filesdown')
        if request.form.get("delete_button"):
            print("delete")
        if request.form.get("download_button"):
            print("download")

        # File Download (Read)
        if filesdown and request.form.get("download_button"):
            print(filesdown)
            for i in filesdown:
                return send_file(public_files + "/" + i + "/" + i, as_attachment=True)

        # File Deletion
        if filesdown and request.form.get("delete_button"):
            for i in os.listdir(public_files):
                if i in filesdown:
                    os.system("mkdir deleted/" + session['username'] + "; mv " + public_files + "/" + i + " deleted/" + session['username'] + "/" + i)

        # File Upload (Write/Append)
        filesup = request.files.getlist('filesup')
        if filesup:
            for i in filesup:
                name = secure_filename(i.filename)
                # Quarantine incoming files
                i.save(app.config['UPLOAD_FOLDER'] + "/" + name)
                # If file is not in the public file directory (i.e. does not exist)
                if name not in os.listdir(public_files):
                     # Make directory for file in public
                    os.system("mkdir " + public_files + "/" + name)
                    # Rsync append to public directory and remove from quarantine.
                    # Also make .version file with owner, primary server, and version number
                    os.system(
                        "rsync " + app.config['UPLOAD_FOLDER'] + "/" + name + " " + public_files + "/" + name + "/" + name +
                        " && rm -f " + app.config['UPLOAD_FOLDER'] + "/" + name +
                        " && touch " + public_files + "/" + name + "/.version" +
                        " && echo \"" + gen_version_string() + "\" > " + public_files + "/" + name + "/.version")
                    for replica in session['replicas']:
                        os.system("sshpass -p 12345 rsync -r " + public_files + "/" + name + "/ cmsc621@" + replica + ":/home/cmsc621/Desktop/" + public_files + "/" + name + "/")

                # Modifying an existing file
                else:
                    print("original server")
                    # Update file version
                    with open(public_files + "/" + name + "/.version", 'r') as file:
                        versioning = file.readlines()

                    for i, line in enumerate(versioning):
                        split_line = line.split(' ')
                        if len(split_line) > 1 and split_line[0] == getip():
                            versioning[i] = split_line[0] + ' ' + str(int(split_line[1]) + 1) + '\n'
                            break

                    os.system("echo \"" + "".join((l for l in versioning if l.strip() != '')) + "\" > " + public_files + "/" + name + "/.version")
                    os.system(
                        "rsync " + app.config['UPLOAD_FOLDER'] + "/" + name + " " + public_files + "/" + name + "/" + name +
                        " && rm -f " + app.config['UPLOAD_FOLDER'] + "/" + name)

    # List the files that are in the public directory on the web page
    to_list = []
    directories = os.listdir(public_files)
    for directory in directories:
        files = os.listdir(public_files + directory)
        for file in files:
            if file != '.version' and file != '.conflict':
                to_list.append(file)
    return render_template('files.html', to_list=to_list, user=session['username'])


@app.route('/down', methods=['GET', 'POST'])
def down():
    # Placeholder for receiving new primary nodes for users
    if request.method == 'POST':
        data2 = request.json
        for user in os.listdir("/home/cmsc621/Desktop/files/"):
            print(user)
            for file in os.listdir("/home/cmsc621/Desktop/files/"+user):
                print(file)
                ip = getip()
                with open("/home/cmsc621/Desktop/files/" + user + "/" + file + "/.version", "r") as file:
                    version = file.readlines()
                if version[1] == ip:
                    for primaryuser in data2:
                        if primaryuser["username"] == user:
                            version[1] = primaryuser["primary"]
                            print(version)
                            os.system("echo \"" + ''.join(version) + "\" > " + "/home/cmsc621/Desktop/files/" + user + "/" + file + "/.version")
                            for replica in primaryuser["replicas"]:
                                os.system("sshpass -p 12345 rsync -r " + "/home/cmsc621/Desktop/files/" + user + "/" + file + "/ cmsc621@" + replica + ":/home/cmsc621/Desktop/files/" + user + "/" + file + "/")
                            break
                    print("BEANS")
        # exit()
        os.system('pkill python; pkill python3')
        # return render_template('index.html')
        exit()
    data = [users, getip()]
    # Request users' new primary nodes
    requests.post('http://' + master + ':25565/resolvedown', json=data)
    return render_template('index.html')

@app.route('/newmaster', methods=['GET', 'POST'])
def newmaster():
    if request.method == 'POST':
        print("new master")
        global master
        print(master)
        master = str(request.data.decode('utf-8'))
        print(master)
    return render_template('index.html')

from flask import abort
import shutil
import time
import threading
import atexit
from random import random
from typing import Union

MIN_SYNC_TIME = 10 # Length of time before a sync attempt will be allowed again after a successful sync with a particular server
SLEEP_TIME = 2 # Sync loop frequency (i.e. additional wait time before attempting syncs again). Lower number ensures sooner syncing if a sync failed previously.
SLEEP_TIME_RAND = 0.3 # Additional random amount added to prevent repeated concurrent sync timing conflicts
syncing_files = []
sync_data = {}
last_known_replicas = []

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

def create_replication_thread():
    global sync_thread

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
        for line in orig_lines:
            version_pair = line.split(' ')
            if len(version_pair) > 1:
                if version_pair[0] in new_versions:
                    version_pair[1] = str(new_versions[version_pair[0]]) + '\n'
            local_file.write(' '.join(version_pair))

def get_curr_version(filepath: str, return_primary: bool = False) -> dict:
    if not os.path.exists(filepath):
        return None
    else:
        versions = {}
        if os.path.exists(os.path.dirname(filepath) + '/.conflict'):
            versions['conflict'] = True

        with open(filepath, 'r') as filereader:
            for i, line in enumerate(filereader):
                version_pair = line.split(' ')
                if i == 1 and return_primary:
                    versions['primary'] = version_pair[0]
                elif len(version_pair) > 1:
                    versions[version_pair[0]] = int(version_pair[1])
        return versions

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
                if i <= 1 or line.strip() == '':
                    continue

                version_pair = line.split(' ')
                data[version_pair[0]] = int(version_pair[1])
        return data

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
        if not os.path.exists(filepath):
            abort(503)

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
        return 'Success'

@app.route('/sync/alive', methods=['GET'])
def check_if_alive():
    return 'Success'

def query_if_alive(ip: str) -> bool:
    return requests.get('http://' + ip + ':25565/sync/alive')

def trigger_sync():
    global thread_active
    thread_active = True
    # Wait until the app is active

    while thread_active:
        for user in os.listdir('files/'):
            for file in os.listdir('files/' + user):
                filepath = 'files/' + user + '/' + file + '/' + file
                versionpath = 'files/' + user + '/' + file + '/.version'

                # Get the current file version vector
                orig_versions = get_curr_version(versionpath, True)
                primary = orig_versions['primary']
                del orig_versions['primary']
                if orig_versions is None:
                    continue

                if versionpath not in sync_data:
                    sync_data[versionpath] = {}
                for ip in orig_versions:
                    if ip not in sync_data[versionpath]:
                        sync_data[versionpath][ip] = 0

                # Sync with the server that has not synced with for the longest time first
                sync_queue = sorted(sync_data[versionpath], key=sync_data[versionpath].get)

                local_versions = orig_versions.copy()
                for ip in sync_queue:
                    if time.time() - sync_data[versionpath][ip] < MIN_SYNC_TIME or ip == getip():
                        continue
                    try:
                        if not query_if_alive(ip):
                            continue
                    except:
                        continue

                    sync_versions(ip, filepath, versionpath, local_versions)

        for user in os.listdir('deleted/'):
            for file in os.listdir('deleted/' + user):
                finish_deletion = True
                versionpath = 'deleted/' + user + '/' + file + '/.version'
                orig_versions = get_curr_version(versionpath)
                if orig_versions is None:
                    continue
                for ip in orig_versions:
                    if ip == getip():
                        continue
                    try:
                        if not query_if_alive(ip):
                            continue
                    except:
                        continue
                    finish_deletion &= requests.post('http://' + ip + ':25565/sync/delete/files/' + user + '/' + file).ok
                # If all requests passed, we are safe to delete the file
                if finish_deletion:
                    shutil.rmtree('deleted/' + user + '/' + file)

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
    print('Syncing on', filepath)

    # if attempt sync succeeds, the other replica will update its syncing_files and sync_data
    if not attempt_sync_with(ip, filepath):
        syncing_files.remove(filepath)
        print('Syncing off', filepath)
        return False

    sync_data[versionpath][ip] = time.time()

    remote_versions = recv_version(ip, versionpath)
    # If we're both in conflict, just do nothing
    if 'conflict' in local_versions and 'conflict' in remote_versions:
        syncing_files.remove(filepath)
        finish_sync_with(ip, filepath)
        return True

    # Create modified versions for easier comparisons
    local_compare = {local_ip:version for local_ip, version in local_versions.items() if local_ip != 'conflict' and local_ip in remote_versions}
    remote_compare = {remote_ip:version for remote_ip, version in remote_versions.items() if remote_ip != 'conflict' and remote_ip in local_versions}
    # If we match versions, do nothing
    if all(version == remote_compare[local_ip] for local_ip, version in local_compare.items()):
        pass
    # If the remote has higher versions than us across the board, we can safely copy remote
    elif all(version <= remote_compare[local_ip] for local_ip, version in local_compare.items()):
        response = recv_sync_file(ip, filepath)
        with open(filepath, 'wb') as file:
            file.write(response.content)
        overwrite_version(versionpath, recv_version(ip, versionpath))
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

        # Make the new vector the latest of the two vectors
        for ip in local_compare:
            local_versions[ip] = max(local_versions[ip], remote_versions[ip])

        if not merge_files(filepath, temp_path):
            local_versions['conflict'] = True

        os.remove(temp_path)

        overwrite_version(versionpath, local_versions)
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

@app.route('/sync/delete/<path:filepath>', methods=['POST'])
def attempt_delete(filepath):
    if not os.path.exists(filepath):
        return 'Success'

    # File is in quarantine (in the middle of a write)
    if os.path.exists(app.config['UPLOAD_FOLDER'] + '/' + os.path.basename(filepath)):
        abort(503)

    # File is already in the middle of a sync
    if filepath in syncing_files:
        abort(503)

    username = os.path.basename(os.path.dirname(os.path.normpath(filepath)))
    filename = os.path.basename(filepath)
    os.system("mkdir deleted/" + username + "; mv " + "files/" + username + '/' + filename + " deleted/" + username + "/" + filename)
    return 'Success'

if __name__ == "__main__":
    # Establish presence in master server's list of nodes
    os.popen("sshpass -p 12345 ssh cmsc621@" + master + " touch /home/cmsc621/Desktop/nodes/" + getip()).read()
    create_replication_thread()
    # app_thread = threading.Thread(app.run, kwargs={'debug':True, 'host':'0.0.0.0', 'port':25565, 'threaded':True})
    # app_thread.start()
    # app_thread.join()
    app.run(debug=True, host="0.0.0.0", port=25565, threaded=True)
