#!/usr/bin/env bash
# One-shot HRMIS install on Ubuntu 22.04 LTS.
# Run as a sudo-capable user. Edit DOMAIN + ADMIN_EMAIL before executing.

set -euo pipefail

DOMAIN="${DOMAIN:-hr.yourcompany.com}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@yourcompany.com}"
APP_USER="${APP_USER:-deploy}"
REPO_URL="${REPO_URL:-https://github.com/yourname/hrmis.git}"
APP_DIR="/opt/hrmis"

echo "==> 1/9  System packages"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
sudo apt-get install -y curl git build-essential nginx ufw \
                        python3.11 python3.11-venv python3.11-dev \
                        ca-certificates gnupg

echo "==> 2/9  Node 20 + Yarn"
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
sudo apt-get install -y nodejs
sudo npm install -g yarn

echo "==> 3/9  MongoDB 7"
if [ ! -f /usr/share/keyrings/mongodb-server-7.0.gpg ]; then
  curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc \
       | sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
fi
echo "deb [signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" \
     | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt-get update -y
sudo apt-get install -y mongodb-org
sudo systemctl enable --now mongod

echo "==> 4/9  Application user + repo"
id "$APP_USER" &>/dev/null || sudo useradd -m -s /bin/bash "$APP_USER"
sudo mkdir -p "$APP_DIR" && sudo chown -R "$APP_USER:$APP_USER" "$APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
else
  sudo -u "$APP_USER" git -C "$APP_DIR" pull
fi

echo "==> 5/9  Python backend"
sudo -u "$APP_USER" bash -c "
  cd $APP_DIR/backend
  python3.11 -m venv venv
  source venv/bin/activate
  pip install --upgrade pip wheel
  pip install -r requirements.txt
"
# .env: copy template if missing
if [ ! -f "$APP_DIR/backend/.env" ]; then
  sudo -u "$APP_USER" cp "$APP_DIR/backend/.env.example" "$APP_DIR/backend/.env"
  JWT=$(openssl rand -hex 32)
  sudo -u "$APP_USER" sed -i "s|REPLACE_WITH_OPENSSL_RAND_HEX_32|$JWT|" "$APP_DIR/backend/.env"
  sudo -u "$APP_USER" sed -i "s|hr.yourcompany.com|$DOMAIN|" "$APP_DIR/backend/.env"
  echo "    !! Edit $APP_DIR/backend/.env to set RESEND_API_KEY and ADMIN_* values"
fi
sudo -u "$APP_USER" mkdir -p "$APP_DIR/uploads"

echo "==> 6/9  React frontend build"
sudo -u "$APP_USER" bash -c "
  cd $APP_DIR/frontend
  echo 'REACT_APP_BACKEND_URL=https://$DOMAIN' > .env.production
  yarn install --frozen-lockfile
  yarn build
"

echo "==> 7/9  systemd unit"
sudo cp "$APP_DIR/deploy/hrmis-backend.service" /etc/systemd/system/hrmis-backend.service
sudo sed -i "s|User=deploy|User=$APP_USER|;s|Group=deploy|Group=$APP_USER|" /etc/systemd/system/hrmis-backend.service
sudo systemctl daemon-reload
sudo systemctl enable --now hrmis-backend

echo "==> 8/9  Nginx + firewall"
sudo cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/hrmis
sudo sed -i "s|hr.yourcompany.com|$DOMAIN|g" /etc/nginx/sites-available/hrmis
sudo ln -sf /etc/nginx/sites-available/hrmis /etc/nginx/sites-enabled/hrmis
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo ufw allow OpenSSH || true
sudo ufw allow 'Nginx Full' || true
yes | sudo ufw enable || true

echo "==> 9/9  HTTPS via Let's Encrypt"
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d "$DOMAIN" --redirect --agree-tos --non-interactive -m "$ADMIN_EMAIL" || \
  echo "    !! certbot failed — check DNS A record for $DOMAIN → this server"

echo ""
echo "✅ Done."
echo "Visit:  https://$DOMAIN"
echo "Health: https://$DOMAIN/api/health"
echo "Edit .env for Resend & admin creds, then: sudo systemctl restart hrmis-backend"
