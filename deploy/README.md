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

## Updates later — safe, one command

Once the app is installed, subsequent updates are handled by a single script
that (1) snapshots MongoDB, (2) snapshots the uploads folder, (3) pulls the
latest code, (4) installs deps, (5) rebuilds the React bundle, (6) restarts
services, and (7) prints a copy-pasteable rollback command:

```bash
sudo bash /opt/hrmis/deploy/update.sh
```

Backups land in `/var/backups/hrmis-db-<timestamp>.gz` and
`/var/backups/hrmis-uploads-<timestamp>.tgz`. Files older than 30 days are
auto-pruned. **No database migrations are needed** — every new feature (WhatsApp
config, timezone, password reset audit) adds new fields/collections; existing
documents are untouched.

If you prefer to run it manually:

```bash
cd /opt/hrmis
sudo -u deploy mongodump --uri="mongodb://127.0.0.1:27017" --db hrmis_database \
    --gzip --archive=/var/backups/hrmis-$(date +%F-%H%M).gz
sudo -u deploy git pull
sudo -u deploy ./backend/venv/bin/pip install -r backend/requirements.txt
(cd frontend && sudo -u deploy yarn install --frozen-lockfile && sudo -u deploy yarn build)
sudo systemctl restart hrmis-backend
sudo systemctl reload nginx
```

### Rollback in one command

If the new build misbehaves, the update script prints an exact rollback for
the run that just happened. General shape:

```bash
# Roll code back
sudo -u deploy git -C /opt/hrmis reset --hard <previous-commit-sha>
sudo -u deploy /opt/hrmis/backend/venv/bin/pip install -r /opt/hrmis/backend/requirements.txt
(cd /opt/hrmis/frontend && sudo -u deploy yarn install --frozen-lockfile && sudo -u deploy yarn build)

# (Optional) restore the database snapshot
sudo mongorestore --uri="mongodb://127.0.0.1:27017" \
    --gzip --archive=/var/backups/hrmis-db-<timestamp>.gz --drop

sudo systemctl restart hrmis-backend && sudo systemctl reload nginx
```

## Daily MongoDB backup (optional)

```bash
sudo crontab -e
# 0 2 * * * /usr/bin/mongodump --uri=mongodb://127.0.0.1:27017 --db hrmis_database --gzip --archive=/var/backups/hrmis-$(date +\%F).gz && find /var/backups -name 'hrmis-*.gz' -mtime +14 -delete
```
