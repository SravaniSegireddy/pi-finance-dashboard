#!/usr/bin/env bash
# 03_webserver.sh — web root + nginx site that serves the dashboard on :8000.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
[ -f .env ] || { echo "No .env yet — run setup/02_configure.sh first."; exit 1; }

echo "==> Creating web root /var/www/finance (owned by you so the sync can write)"
sudo mkdir -p /var/www/finance
sudo chown "$USER":"$USER" /var/www/finance

# placeholder page so the URL works before the first sync
if [ ! -f /var/www/finance/dashboard.html ]; then
  printf '%s\n' "<html><body style='font-family:sans-serif;padding:48px;color:#334'>Dashboard not generated yet — run <b>bash setup/05_sync_now.sh</b>.</body></html>" \
    > /var/www/finance/dashboard.html
fi

echo "==> Installing nginx site"
sudo tee /etc/nginx/sites-available/finance >/dev/null <<'EOF'
server {
    listen 8000;
    server_name _;
    root /var/www/finance;
    index dashboard.html;

    auth_basic "Household Spend";
    auth_basic_user_file /etc/nginx/.htpasswd-finance;

    location / {
        try_files /dashboard.html =404;
        add_header Cache-Control "no-store";
    }
}
EOF
sudo ln -sf /etc/nginx/sites-available/finance /etc/nginx/sites-enabled/finance
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl enable nginx >/dev/null 2>&1 || true

IP="$(hostname -I | awk '{print $1}')"
echo
echo "✓ nginx is serving on port 8000."
echo "  Test from a device on your wifi:  http://${IP}:8000  (log in with your dashboard user/password)"
echo
echo "Next:  bash setup/04_link_cards.sh"
