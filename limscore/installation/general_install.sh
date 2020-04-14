#!/usr/bin/env bash

THREADS=""
APP=""
EMAIL=""

mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal


sudo pip3 install boto3
sudo pip3 install waitress
sudo pip3 install flask


sudo useradd flask --shell /usr/bin/false
sudo usermod flask -L

sudo mkdir /home/flask/$APP_prod
sudo chown flask /home/flask/$APP_prod
cat >$APP.conf <<EOF 
DB_URL = "postgresql://flask@localhost/$APP_prod"
EOF
sudo chown flask $APP.cfg
sudo mv $APP.conf /home/flask/$APP_prod


ssh-keygen -t rsa -b 4096 -C "$EMAIL"
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_rsa
cat ~/.ssh/id_rsa.pub

git clone git@github.com:eawilson/limscore.git
cd limscore
sudo python3 setup.py develop
cd ..

git clone git@github.com:eawilson/aireal.git
cd aireal
sudo python3 setup.py develop
cd ..


cat >$APP.service <<EOF 
[Unit]
Description=AIREAL web app
After=network.target

[Service]
User=flask
WorkingDirectory=~/home/flask/$APP_prod
ExecStart=aireal_serve
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo mv $APP.service /etc/systemd/system/$APP.service

sudo systemctl daemon-reload
sudo systemctl start $APP
