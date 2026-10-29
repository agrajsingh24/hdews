#!/bin/sh
# Container entrypoint. If started as root (the default), make the SQLite database directory writable by the
# unprivileged 'hdews' user (platform disks and Docker volumes may be mounted root-owned), then drop
# privileges permanently. The application itself never runs as root.
set -eu
APP_USER="${HDEWS_RUN_AS:-hdews}"
if [ "$(id -u)" = "0" ]; then
  case "${DATABASE_URL:-}" in
    sqlite:///*)
      db_dir=$(dirname "${DATABASE_URL#sqlite:///}")
      mkdir -p "$db_dir"
      chown "$APP_USER:$APP_USER" "$db_dir"
      find "$db_dir" -maxdepth 1 -name 'hdews.db*' -exec chown "$APP_USER:$APP_USER" {} + 2>/dev/null || true
      ;;
  esac
  exec setpriv --reuid="$APP_USER" --regid="$APP_USER" --init-groups --no-new-privs "$@"
fi
exec "$@"
