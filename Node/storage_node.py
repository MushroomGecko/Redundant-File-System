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

users = []
master = "192.168.1.3"

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
    if request.method == 'POST':
        user_data = request.json
        users.append(user_data[0])
        print(users)
        return render_template('index.html')

    if 'ip' in session and 'username' in session:
        return redirect('/files')

    for i in users:
        # Establish user's session cookies
        if str(request.remote_addr) == i['ip']:
            session['ip'] = i['ip']
            session['replicas'] = i['replicas']
            session['username'] = i['username']
            return redirect('/files')
    return redirect('http://' + master + ':25565')


@app.route('/files', methods=['GET', 'POST'])
def files_index():
    public_files = 'files/'
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
                # Quarantine files
                i.save(app.config['UPLOAD_FOLDER'] + "/" + name)
                if name not in os.listdir(public_files):
                    # Make directory for file in public
                    os.system("mkdir " + public_files + "/" + name)
                    # Rsync append to public directory and remove from quarantine.
                    # Also make .version file with owner, primary server, and version number
                    os.system(
                        "rsync " + app.config['UPLOAD_FOLDER'] + "/" + name + " " + public_files + "/" + name + "/" + name +
                        " && rm -f " + app.config['UPLOAD_FOLDER'] + "/" + name +
                        " && touch " + public_files + "/" + name + "/.version" +
                        " && echo \"" + session['username'] + "\n" + getip() + "\" > " + public_files + "/" + name + "/.version")
                    for replica in session['replicas']:
                        os.system("sshpass -p 12345 rsync " + public_files + "/" + name + " cmsc621@" + replica + ":/home/cmsc621/Desktop/" + public_files + "/" + name)
                else:
                    versioning = os.popen("cat " + public_files + "/" + name + "/.version").read().split("\n")
                    if versioning[1] != getip():
                        print("not original server")
                    for replica in session['replicas']:
                        os.system("sshpass -p 12345 rsync -r " + public_files + "/" + name + " cmsc621@" + replica + ":/home/cmsc621/Desktop/" + public_files + "/" + name)

    to_list = []
    directories = os.listdir(public_files)
    for directory in directories:
        files = os.listdir(public_files + directory)
        for file in files:
            if file != '.version':
                to_list.append(file)
    return render_template('files.html', to_list=to_list, user=session['username'])


if __name__ == "__main__":
    # os.popen("sshpass -p 12345 ssh cmsc621@" + master + " touch /home/cmsc621/Desktop/" + getip()).read()
    app.run(debug=True, host="0.0.0.0", port=25565, threaded=True)
