#!/usr/bin/env bash
# Run only after the owner explicitly approves public TCP 80/443 exposure.
set -Eeuo pipefail
test "${1:-}" = '--approved-public-access' || { echo 'Explicit public-access approval required'; exit 1; }
ip=47.82.118.171
sudo test -s /etc/skilltree/evaluators.htpasswd
test -x /opt/skilltree-certbot/bin/certbot
test ! -e /etc/nginx/conf.d/skilltree-public.conf
sudo install -d -m 755 /var/www/skilltree-acme/.well-known/acme-challenge
sudo tee /etc/nginx/conf.d/skilltree-public.conf >/dev/null <<'NGINX'
server {
    listen 80;
    server_name 47.82.118.171;
    server_tokens off;
    location ^~ /.well-known/acme-challenge/ { root /var/www/skilltree-acme; }
    location / { return 404; }
}
NGINX
sudo nginx -t
sudo systemctl reload nginx
sudo /opt/skilltree-certbot/bin/certbot certonly --non-interactive --agree-tos --register-unsafely-without-email --preferred-profile shortlived --webroot --webroot-path /var/www/skilltree-acme --ip-address "$ip" --cert-name skilltree-ip
sudo python3 - <<'PY'
from pathlib import Path
base=Path('/etc/nginx/conf.d/skilltree-loopback.conf').read_text()
body=base[base.index('server {'):].replace('listen 127.0.0.1:8080;', '''listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/skilltree-ip/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/skilltree-ip/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;''')
http='''server {
    listen 80;
    server_name 47.82.118.171;
    server_tokens off;
    location ^~ /.well-known/acme-challenge/ { root /var/www/skilltree-acme; }
    location / { return 301 https://47.82.118.171$request_uri; }
}
'''
Path('/etc/nginx/conf.d/skilltree-public.conf').write_text(http+body)
PY
sudo nginx -t
sudo systemctl reload nginx
sudo install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
printf '#!/bin/sh\n/usr/sbin/nginx -t && /usr/bin/systemctl reload nginx\n' | sudo tee /etc/letsencrypt/renewal-hooks/deploy/skilltree-nginx >/dev/null
sudo chmod 755 /etc/letsencrypt/renewal-hooks/deploy/skilltree-nginx
sudo tee /etc/systemd/system/skilltree-certbot.service >/dev/null <<'UNIT'
[Unit]
Description=Renew SkillTree short-lived IP certificate
[Service]
Type=oneshot
ExecStart=/opt/skilltree-certbot/bin/certbot renew --quiet
UNIT
sudo tee /etc/systemd/system/skilltree-certbot.timer >/dev/null <<'UNIT'
[Unit]
Description=Check IP certificate renewal twice per day
[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=900
Persistent=true
[Install]
WantedBy=timers.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now skilltree-certbot.timer
echo 'Public HTTPS configured; verify from outside this server before sharing.'
