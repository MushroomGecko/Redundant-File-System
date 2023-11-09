from flask import Flask, render_template, request, send_file, session, redirect
from flask_sock import Sock
import os
import subprocess
import socket
import json
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "quarantine/"
app.config['SECRET_KEY'] = "Your_secret_string"
app.config['SOCK_SERVER_OPTIONS'] = {'ping_interval': 25}
sock = Sock(app)

# List of active users
users = []
# IP of the master server
master = "192.168.1.3"

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
        # File Download (Read)
        filesdown = request.form.getlist('filesdown')
        if filesdown:
            print(filesdown)
            for i in filesdown:
                return send_file(public_files + "/" + i + "/" + i, as_attachment=True)

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
                        " && echo \"" + session['username'] + "\n" + getip() + "\n1\" > " + public_files + "/" + name + "/.version")
                    for replica in session['replicas']:
                        os.system("sshpass -p 12345 rsync -r " + public_files + "/" + name + " cmsc621@" + replica + ":/home/cmsc621/Desktop/" + public_files + "/" + name)

                # Modifying an existing file
                else:
                    print("original server")
                    # Update file version
                    versioning = os.popen("cat " + public_files + "/" + name + "/.version").read().split("\n")
                    os.system("echo \"" + versioning[0] + "\n" + versioning[1] + "\n" + str(int(versioning[2])+1) + "\" > " + public_files + "/" + name + "/.version")
                    versioning = os.popen("cat " + public_files + "/" + name + "/.version").read().split("\n")
                    # If file originates from a different node
                    if versioning[1] != getip():
                        print("not original server")
                    # If this is the original node, send file to replication nodes
                    else:
                        for replica in session['replicas']:
                            os.system("sshpass -p 12345 rsync -r " + public_files + "/ cmsc621@" + replica + ":/home/cmsc621/Desktop/" + public_files + "/" + name)
    # List the files that are in the public directory on the web page
    to_list = []
    directories = os.listdir(public_files)
    for directory in directories:
        files = os.listdir(public_files + directory)
        for file in files:
            if file != '.version':
                to_list.append(file)
    return render_template('files.html', to_list=to_list, user=session['username'])


if __name__ == "__main__":
    # Establish presence in master server's list of nodes
    # os.popen("sshpass -p 12345 ssh cmsc621@" + master + " touch /home/cmsc621/Desktop/" + getip()).read()
    app.run(debug=True, host="0.0.0.0", port=25565, threaded=True)
