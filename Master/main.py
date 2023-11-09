import json

from flask import Flask, render_template, request, send_file, session, redirect, url_for
import requests
from flask_sock import Sock
import os
import subprocess
import socket

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "files/"
app.config['SECRET_KEY'] = "Your_secret_string"
app.config['SOCK_SERVER_OPTIONS'] = {'ping_interval': 25}
sock = Sock(app)

nodes = os.listdir('nodes/')


@app.route('/', methods=['GET', 'POST'])
def index():
    if 'ip' not in session:
        if request.method == "POST":
            # Get the username and IP of a user connecting
            username = request.form.get("username")
            if username != '':
                session['ip'] = request.remote_addr
                session['username'] = username
                print("here")
                sessionavg = {}
                # Find session node with the lowest ping
                x = 1
                for i in nodes:
                    if x > 5:
                        break
                    ping = os.popen("sshpass -p 12345 ssh cmsc621@" + i + " ping -c 1 " + str(session['ip'])).read()
                    avg = str(ping.split("rtt")[1]).split()[2].split("/")[1]
                    sessionavg[i] = avg
                    x += 1

                if username not in os.listdir('users/'):
                    os.system("touch users/" + username + " && echo \"" + str(list(sessionavg.keys())) + "\" > users/" + username)
                else:
                    file = open("users/" + username, "r").read()
                    print(file)
                    rep = list(json.loads(file.replace('\'', '"')))
                    for i in sessionavg.keys():
                        if i not in rep:
                            rep.append(i)
                    os.system("echo \"" + str(rep) + "\" > users/" + username)
                primary = min(zip(sessionavg.values(), sessionavg.keys()))[1]
                sessionavg.pop(primary)
                replicas = list(sessionavg.keys())


                session['primary'] = primary
                session['replicas'] = replicas
                print(session['primary'], session['replicas'])

                data = [{"username": session['username'], "ip": session['ip'], "replicas": session['replicas']}]
                requests.post('http://' + session['primary'] + ':25565', json=data)
                return redirect('http://' + session['primary'] + ':25565')
            return redirect('http://' + session['primary'] + ':25565')
        return render_template("index.html")
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=25565, threaded=True)