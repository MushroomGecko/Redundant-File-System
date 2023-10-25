from flask import Flask, render_template, request, send_file, session, redirect
from flask_sock import Sock
import os
import subprocess
import socket

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "files/"
app.config['SECRET_KEY'] = "Your_secret_string"
app.config['SOCK_SERVER_OPTIONS'] = {'ping_interval': 25}
sock = Sock(app)

nodes = ['192.168.1.5']


@app.route('/', methods=['GET', 'POST'])
def index():
    if 'ip' not in session:
        session['ip'] = request.remote_addr
        print("here")
        sessionavg = {}
        for i in nodes:
            ping = os.popen("sshpass -p 12345 ssh cmsc621@" + i + " ping -c 3 " + str(session['ip'])).read()
            avg = str(ping.split("rtt")[1]).split()[2].split("/")[1]
            sessionavg[i] = avg
        sessionnode = min(zip(sessionavg.values(), sessionavg.keys()))[1]
        session['node'] = sessionnode
        return redirect('http://'+session['node']+':25565')
    return redirect('http://'+session['node']+':25565')


if __name__ == "__main__":

    app.run(debug=True, host="0.0.0.0", port=25565, threaded=True)
