import json

from flask import Flask, render_template, request, send_file, session, redirect, url_for
import requests
from flask_sock import Sock
import os
import subprocess
import socket
import threading

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "files/"
app.config['SECRET_KEY'] = "Your_secret_string"
app.config['SOCK_SERVER_OPTIONS'] = {'ping_interval': 25}
sock = Sock(app)

resultsarray = []

@app.route('/', methods=['GET', 'POST'])
def index():
    nodes = os.listdir('nodes/')
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
                    print(ping)
                    avg = str(ping.split("rtt")[1]).split()[2].split("/")[1]
                    sessionavg[i] = avg
                    x += 1

                sessionavg = dict(sorted(sessionavg.items(), key=lambda item: item[1]))
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
                print(dict(sorted(sessionavg.items(), key=lambda x: x[1])))
                print(sessionavg)
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


@app.route('/resolvedown', methods=['GET', 'POST'])
def resolvedown():
    if request.method == 'POST':
        print("Down request")
        # Get the post request from the downed server
        data = request.json
        # print(data)
        # Get IP of downed server
        downednode = data[1]
        print(downednode)
        os.system("rm -f nodes/" + downednode)

        # Store all users with new primary replica in global array (threading can't return values)
        global resultsarray
        resultsarray = []

        # Remove downed node from client replica list
        # threadarray = []
        for user in os.listdir('users'):
            openfile = open("users/" + user, "r")
            file = openfile.read()
            openfile.close()
            # print(file)
            rep = list(json.loads(file.replace('\'', '"')))
            if downednode in rep:
                rep.remove(downednode)
                os.system("echo \"" + str(rep) + "\" > users/" + user)
                # print(type(user))
                # threadarray.append(threading.Thread(target=find_new_server, args=(user,)))
            openfile = open("users/" + user, "r")
            file = openfile.read()
            openfile.close()
            usernodes = list(json.loads(file.replace('\'', '"')))
            print(user, usernodes)
            # If the user has any remaining servers in their array
            if usernodes:
                # If the user is currently in a session, change the primary server
                if session:
                    session["primary"] = usernodes[0]
                    # If the user has more than one server listed in their array
                    if usernodes[1]:
                        session["replicas"] = usernodes[1:]
                # Prepare data to send to down server
                resultsarray.append({"username": user, "primary": usernodes[0], "replicas": usernodes})


        # See who exists in downed node to get ready to transfer user files to new primary servers
        # print("Getting Results...")
        # for thread in threadarray:
        #     thread.start()
        #     thread.join()
        print(resultsarray)
        requests.post('http://' + downednode + ':25565/down', json=resultsarray)
    return render_template("index.html")


def find_new_server(user):
    global resultsarray
    # Get user data
    file = open("users/" + user, "r").read()
    rep = list(json.loads(file.replace('\'', '"')))
    sessionavg = {}

    # If user does not have any replicas, oh well
    if not rep:
        return 0

    # Find lowest ping existing replica for new primary server
    x = 1
    for i in rep:
        # print(i)
        if x > 5:
            break
        ping = os.popen("sshpass -p 12345 ssh cmsc621@" + i + " ping -c 1 " + str(i)).read()
        # print(ping)
        avg = str(ping.split("rtt")[1]).split()[2].split("/")[1]
        sessionavg[i] = avg
        x += 1
    primary = min(zip(sessionavg.values(), sessionavg.keys()))[1]
    sessionavg.pop(primary)
    replicas = list(sessionavg.keys())

    # If a user is in a session, update session
    if session:
        session['primary'] = primary
        session['replicas'] = replicas
    # Add user stuff to results array
    resultsarray.append([user, primary])


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=25565, threaded=True)
