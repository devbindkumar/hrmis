# HRMIS — Self-host on Ubuntu 22.04

This folder ships with everything you need to deploy the HRMIS to your own
Linux VPS. No Emergent services are required.

## What got replaced
- **Object storage**: now a plain local filesystem at `<repo>/uploads` (or
  `UPLOAD_DIR` from `.env`). Resume + logo uploads write to disk.
- **`emergentintegrations` Python package**: removed. The backend imports
  nothing from it.
- **Heavy `pip freeze` dependency tree**: replaced with a 13-line minimal
  `requirements.txt` containing only what the code actually uses.

## What still uses an outside service
- **Resend** for transactional emails. Free tier works; verify a domain to
  send to anyone other than yourself.
- **MongoDB**: bundled into the install script (Mongo 7 on the same VPS).
  Swap `MONGO_URL` for Atlas if preferred.

## TL;DR — automated install

```bash
# 1) Point DNS A record:  hr.yourcompany.com → VPS IP
# 2) SSH to the VPS as a sudo-capable user
git clone https://github.com/<you>/<your-repo>.git /tmp/hrmis-source
cd /tmp/hrmis-source/deploy
sudo DOMAIN=hr.yourcompany.com \
     ADMIN_EMAIL=you@yourcompany.com \
     REPO_URL=https://github.com/<you>/<your-repo>.git \
     bash install.sh
```

The script handles: system packages, Node 20, MongoDB 7, app user, repo
clone, Python venv, backend install, React build, systemd unit, Nginx,
firewall, Let's Encrypt HTTPS.

After it finishes:

```bash
sudo nano /opt/hrmis/backend/.env       # set RESEND_API_KEY + ADMIN_*
sudo systemctl restart hrmis-backend
```

Visit `https://hr.yourcompany.com`, sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`
from the `.env`, then create your real super-admin from Employees → Add.

## Manual install (in case the script fails partway)

See `STEPS.md` in this folder.

## Updates later

```bash
cd /opt/hrmis
sudo -u deploy git pull
cd backend && sudo -u deploy ./venv/bin/pip install -r requirements.txt
sudo systemctl restart hrmis-backend
cd ../frontend && sudo -u deploy yarn install && sudo -u deploy yarn build
sudo systemctl reload nginx
```

## Daily MongoDB backup (optional)

```bash
sudo crontab -e
# 0 2 * * * /usr/bin/mongodump --uri=mongodb://127.0.0.1:27017 --db hrmis_database --gzip --archive=/var/backups/hrmis-$(date +\%F).gz && find /var/backups -name 'hrmis-*.gz' -mtime +14 -delete
```
