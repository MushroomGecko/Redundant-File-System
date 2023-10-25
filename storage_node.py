from flask import Flask, render_template, request, send_file, session
from flask_sock import Sock
import os
import subprocess
import socket

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "files/"
app.config['SECRET_KEY'] = "Your_secret_string"
app.config['SOCK_SERVER_OPTIONS'] = {'ping_interval': 25}
sock = Sock(app)

nodes = []


@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template("index.html", ip=str(os.popen('ip a | grep -w "inet"').read()).split('inet')[2])


if __name__ == "__main__":

    app.run(debug=True, host="0.0.0.0", port=25565, threaded=True)
