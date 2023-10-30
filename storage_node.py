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
        if str(request.remote_addr) == i['ip']:
            session['ip'] = i['ip']
            session['username'] = i['username']
            return redirect('/files')
    return redirect('http://' + master + ':25565')


@app.route('/files', methods=['GET', 'POST'])
def files_index():
    public_files = 'files/'

    if request.method == "POST":
        filesdown = request.form.getlist('filesdown')
        if filesdown:
            print(filesdown)
            for i in filesdown:
                return send_file(public_files + "/" + i + "/" + i, as_attachment=True)

        filesup = request.files.getlist('filesup')
        if filesup:
            for i in filesup:
                name = secure_filename(i.filename)

                i.save(app.config['UPLOAD_FOLDER'] + "/" + name)
                os.system("mkdir " + public_files + "/" + name)
                os.system("rsync " + app.config['UPLOAD_FOLDER'] + "/" + name + " " + public_files + "/" + name +
                          " && rm -f " + app.config['UPLOAD_FOLDER'] + "/" + name)


    to_list = []
    directories = os.listdir(public_files)
    for directory in directories:
        files = os.listdir(public_files + directory)
        for file in files:
            if file != '.version':
                to_list.append(file)
    return render_template('files.html', to_list=to_list, user=session['username'])


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=25565, threaded=True)
