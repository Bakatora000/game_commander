#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${GC_REPO_URL:-https://github.com/Bakatora000/game_commander.git}"
REPO_BRANCH="${GC_REPO_BRANCH:-main}"
REPO_DIR="${GC_REPO_DIR:-/opt/game-commander}"
DOMAIN="${GC_DOMAIN:-$(hostname -f 2>/dev/null || hostname)}"
ADMIN_LOGIN="${GC_ADMIN_LOGIN:-admin}"
ADMIN_PASSWORD="${GC_ADMIN_PASSWORD:-}"
SSL_MODE="${GC_SSL_MODE:-none}"

detect_sys_user() {
  if [[ -n "${GC_SYS_USER:-}" ]]; then
    echo "$GC_SYS_USER"
    return 0
  fi
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    echo "$SUDO_USER"
    return 0
  fi
  getent passwd | awk -F: '$3 >= 1000 && $1 != "nobody" && $6 ~ "^/home/" { print $1; exit }'
}

SYS_USER="$(detect_sys_user || true)"

if [[ $EUID -ne 0 ]]; then
  echo "Lance ce script en root : sudo bash install_hub.sh" >&2
  exit 1
fi

if [[ -z "$SYS_USER" ]]; then
  echo "Impossible de déterminer l'utilisateur système. Définit GC_SYS_USER." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl

if [[ -d "$REPO_DIR/.git" ]]; then
  git -C "$REPO_DIR" fetch origin "$REPO_BRANCH"
  git -C "$REPO_DIR" checkout -q "$REPO_BRANCH"
  git -C "$REPO_DIR" reset --hard "origin/$REPO_BRANCH"
else
  rm -rf "$REPO_DIR"
  git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" "$REPO_DIR"
fi

CMD=(bash "$REPO_DIR/game_commander.sh" bootstrap-hub --sys-user "$SYS_USER" --domain "$DOMAIN" --admin-login "$ADMIN_LOGIN" --ssl-mode "$SSL_MODE")
if [[ -n "$ADMIN_PASSWORD" ]]; then
  CMD+=(--admin-password "$ADMIN_PASSWORD")
fi
"${CMD[@]}"
