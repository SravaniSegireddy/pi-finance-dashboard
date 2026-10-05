#!/usr/bin/env bash
# 01_install.sh — system packages + Python virtual environment.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "==> Updating package lists"
sudo apt update

echo "==> Installing nginx + Python tooling (openssl is already present)"
sudo apt install -y nginx python3-venv python3-pip

echo "==> Creating Python virtual environment (.venv)"
[ -d .venv ] || python3 -m venv .venv

echo "==> Installing Python dependencies"
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install -r requirements.txt

echo
echo "✓ Install complete. Next:  bash setup/02_configure.sh"
