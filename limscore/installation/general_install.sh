#!/usr/bin/env bash

THREADS=""
APP=""

mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal


sudo pip3 install boto3
sudo pip3 install waitress
sudo pip3 install flask


sudo useradd flask --shell /usr/bin/false
sudo usermod flask -L

sudo mkdir /home/flask/$APP_prod
sudo chowm flask /home/flask/$APP_prod
cat >$APP.conf <<EOF 
DB_URL = "postgresql://flask@localhost/$APP_prod"
EOF
sudo chown flask $APP.conf
sudo mv $APP.conf /home/flask


cat >$APP.service <<EOF 
[Unit]
Description=AIREAL web app
After=network.target

[Service]
User=flask
WorkingDirectory=~/home/flask
ExecStart=waitress-serve --listen=127.0.0.1:8080 --url-scheme=https --threads $THREADS $APP:create_app(/home/flask/$APP_prod)
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo mv $APP.service /etc/systemd/system/$APP.service

sudo systemctl demon-reload
sudo systemctl start $APP
