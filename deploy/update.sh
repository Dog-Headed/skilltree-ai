#!/usr/bin/env bash
# Intended for an approved, protected GitHub Actions production environment.
set -Eeuo pipefail
umask 077
cd /home/admin/skilltree-ai
exec 9>/home/admin/.skilltree-deploy.lock
flock -n 9 || { echo 'Another deployment is in progress'; exit 1; }
test -z "$(git status --porcelain)" || { echo 'Server has local changes; deployment refused'; exit 1; }
git fetch origin main
target="${1:-$(git rev-parse origin/main)}"
[[ "$target" =~ ^[0-9a-f]{40}$ ]] || { echo 'Use a full commit hash'; exit 1; }
git merge-base --is-ancestor HEAD "$target"
git merge-base --is-ancestor "$target" origin/main
old=$(git rev-parse HEAD)
if git diff --name-only "$old" "$target" -- deploy requirements.txt | grep -q .; then
    echo 'Deployment infrastructure or dependencies changed; manual reviewed deployment required'
    exit 1
fi
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir="/home/admin/skilltree-backups/$stamp"
env_hash=$(sha256sum .env | cut -d' ' -f1)
sudo systemctl stop skilltree
trap 'sudo systemctl start skilltree' EXIT
.venv/bin/python deploy/backup.py "$PWD" "$backup_dir"
git merge --ff-only "$target"
test "$env_hash" = "$(sha256sum .env | cut -d' ' -f1)"
.venv/bin/python -c 'from app.v3.learning_api import create_learning_app; create_learning_app()'
printf 'SKILLTREE_COMMIT=%s\nSKILLTREE_DAILY_WRITES=120\nSKILLTREE_ACCOUNT_DAILY_WRITES=40\n' "$target" | sudo tee /etc/skilltree/runtime.env >/dev/null
sudo systemctl start skilltree
for attempt in $(seq 1 20); do
    if curl --fail --silent --max-time 5 http://127.0.0.1:8080/healthz; then
        echo " Deployed $target; backup $backup_dir"
        exit 0
    fi
    sleep 2
done
echo "Health check failed. Previous commit: $old. Backup: $backup_dir. Preserve new data before manual rollback."
exit 1
