#!/usr/bin/env bash
# HRMIS — safe in-place update for a Linux VPS.
#
# What it does (in this exact order):
#   1. Snapshots MongoDB into /var/backups/hrmis-db-<ts>.gz
#   2. Snapshots the uploads folder into /var/backups/hrmis-uploads-<ts>.tgz
#   3. Pulls latest code
#   4. Installs new Python & JS deps
#   5. Rebuilds the React bundle
#   6. Restarts backend + reloads Nginx
#
# Zero database migrations are needed — all new fields/collections are additive.
# Your existing employees, companies, attendance, leave, WFH, payslips, etc.
# are untouched.
#
# Usage:  sudo bash /opt/hrmis/deploy/update.sh
# Rollback:  see the "Rollback" section printed at the end of a successful run.

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/hrmis}"
APP_USER="${APP_USER:-deploy}"
DB_NAME="${DB_NAME:-hrmis_database}"
MONGO_URI="${MONGO_URI:-mongodb://127.0.0.1:27017}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups}"
KEEP_BACKUPS_DAYS="${KEEP_BACKUPS_DAYS:-30}"

TS="$(date +%F-%H%M)"
DB_SNAP="$BACKUP_DIR/hrmis-db-$TS.gz"
UP_SNAP="$BACKUP_DIR/hrmis-uploads-$TS.tgz"

log()  { printf '\033[1;36m[hrmis-update]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[hrmis-update ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

# 0) Sanity
[[ $EUID -eq 0 ]] || fail "Please run with sudo."
[[ -d $APP_DIR/.git ]] || fail "$APP_DIR is not a git checkout — is HRMIS installed here?"
command -v mongodump >/dev/null || fail "mongodump not found. Install mongodb-database-tools."
command -v yarn      >/dev/null || fail "yarn not found."
mkdir -p "$BACKUP_DIR"

# 1) Snapshot MongoDB
log "1/6  MongoDB snapshot → $DB_SNAP"
mongodump --uri="$MONGO_URI" --db "$DB_NAME" --gzip --archive="$DB_SNAP"
DB_SIZE=$(du -h "$DB_SNAP" | cut -f1)
log "     · size $DB_SIZE"

# 2) Snapshot uploads (resumes, logos, backgrounds)
if [[ -d $APP_DIR/backend/uploads ]]; then
    log "2/6  Uploads snapshot → $UP_SNAP"
    tar czf "$UP_SNAP" -C "$APP_DIR" backend/uploads
    UP_SIZE=$(du -h "$UP_SNAP" | cut -f1)
    log "     · size $UP_SIZE"
else
    log "2/6  No backend/uploads folder yet — skipping uploads snapshot."
fi

# 3) Pull latest code
log "3/6  git pull"
cd "$APP_DIR"
CURRENT_HEAD=$(sudo -u "$APP_USER" git rev-parse HEAD)
sudo -u "$APP_USER" git fetch --prune
sudo -u "$APP_USER" git pull --ff-only
NEW_HEAD=$(sudo -u "$APP_USER" git rev-parse HEAD)
if [[ "$CURRENT_HEAD" == "$NEW_HEAD" ]]; then
    log "     · already at latest commit $NEW_HEAD"
else
    log "     · $CURRENT_HEAD → $NEW_HEAD"
fi

# 4) Backend deps
log "4/6  Backend Python dependencies"
sudo -u "$APP_USER" "$APP_DIR/backend/venv/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"

# 5) Frontend build
log "5/6  Frontend build"
cd "$APP_DIR/frontend"
sudo -u "$APP_USER" yarn install --frozen-lockfile --silent
sudo -u "$APP_USER" yarn build

# 6) Restart services
log "6/6  Restarting services"
systemctl restart hrmis-backend
sleep 2
systemctl reload nginx || systemctl restart nginx

# Health check
sleep 1
if curl -sfo /dev/null "http://127.0.0.1:8001/api/health" \
   || curl -sfo /dev/null "http://127.0.0.1:8001/docs"; then
    log "     · backend responding"
else
    fail "Backend not responding on :8001. Check: journalctl -u hrmis-backend -n 100"
fi

# Housekeeping — trim old backups
find "$BACKUP_DIR" -maxdepth 1 -name 'hrmis-db-*.gz'      -mtime +"$KEEP_BACKUPS_DAYS" -delete || true
find "$BACKUP_DIR" -maxdepth 1 -name 'hrmis-uploads-*.tgz' -mtime +"$KEEP_BACKUPS_DAYS" -delete || true

# ─────────────────────────────────────────────────────────────
cat <<EOF

$(printf '\033[1;32m✔ HRMIS update complete\033[0m')

  Commit:   $NEW_HEAD
  DB dump:  $DB_SNAP
  Uploads:  ${UP_SNAP:-<skipped>}

Rollback (if something broke):
  sudo -u $APP_USER git -C $APP_DIR reset --hard $CURRENT_HEAD
  sudo -u $APP_USER $APP_DIR/backend/venv/bin/pip install -r $APP_DIR/backend/requirements.txt
  (cd $APP_DIR/frontend && sudo -u $APP_USER yarn install --frozen-lockfile && sudo -u $APP_USER yarn build)
  sudo mongorestore --uri="$MONGO_URI" --gzip --archive="$DB_SNAP" --drop
  sudo systemctl restart hrmis-backend && sudo systemctl reload nginx

EOF
