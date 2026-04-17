#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="buspcrt-updater.service"
TIMER_NAME="buspcrt-updater.timer"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
TIMER_PATH="/etc/systemd/system/${TIMER_NAME}"

log_info() {
  echo "[INFO] $*"
}

log_error() {
  echo "[ERROR] $*" >&2
}

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    log_error "Run as root (or via sudo)."
    exit 1
  fi
}

abs_path() {
  local p="$1"
  if command -v realpath >/dev/null 2>&1; then
    realpath "$p"
  else
    readlink -f "$p"
  fi
}

read_env_value() {
  local env_file="$1"
  local key="$2"
  awk -F= -v key="$key" '
    $0 ~ "^[[:space:]]*"key"=" {
      sub(/^[^=]*=/, "", $0)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0)
      print $0
      exit
    }
  ' "$env_file"
}

usage() {
  cat <<'EOF'
Usage:
  updater_service.sh install --project-root <path> --env <config.env>
  updater_service.sh uninstall
EOF
}

install_service() {
  local project_root="" env_file=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project-root) project_root="$2"; shift 2 ;;
      --env) env_file="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) log_error "Unknown option: $1"; usage; exit 1 ;;
    esac
  done

  [[ -n "$project_root" ]] || { log_error "--project-root is required"; exit 1; }
  [[ -n "$env_file" ]] || { log_error "--env is required"; exit 1; }

  project_root="$(abs_path "$project_root")"
  env_file="$(abs_path "$env_file")"

  [[ -d "$project_root" ]] || { log_error "Project root not found: $project_root"; exit 1; }
  [[ -f "$env_file" ]] || { log_error "Env file not found: $env_file"; exit 1; }
  [[ -f "$project_root/scripts/updater.sh" ]] || { log_error "Updater script not found: $project_root/scripts/updater.sh"; exit 1; }

  local update_interval
  update_interval="$(read_env_value "$env_file" "UPDATE_INTERVAL")"
  if [[ -z "$update_interval" ]]; then
    update_interval="1h"
  fi

  log_info "Writing unit: $SERVICE_PATH"
  cat >"$SERVICE_PATH" <<EOF
[Unit]
Description=BusPCRT Updater Service
After=network.target

[Service]
Type=oneshot
User=root
Group=root
WorkingDirectory=${project_root}
EnvironmentFile=${env_file}
ExecStart=/bin/bash ${project_root}/scripts/updater.sh --config-env-file ${env_file}
StandardOutput=journal
StandardError=journal
EOF

  log_info "Writing timer: $TIMER_PATH"
  cat >"$TIMER_PATH" <<EOF
[Unit]
Description=Run BusPCRT updater periodically

[Timer]
OnBootSec=2min
OnUnitActiveSec=${update_interval}
Persistent=true
Unit=${SERVICE_NAME}

[Install]
WantedBy=timers.target
EOF

  log_info "Reloading systemd"
  systemctl daemon-reload
  log_info "Enabling and starting ${TIMER_NAME}"
  systemctl enable --now "$TIMER_NAME"
  log_info "Done. Check: systemctl status ${SERVICE_NAME} && systemctl status ${TIMER_NAME}"
}

uninstall_service() {
  log_info "Stopping and disabling ${TIMER_NAME}/${SERVICE_NAME} (if exists)"
  systemctl disable --now "$TIMER_NAME" >/dev/null 2>&1 || true
  systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true

  if [[ -f "$TIMER_PATH" ]]; then
    log_info "Removing unit file: $TIMER_PATH"
    rm -f "$TIMER_PATH"
  fi
  if [[ -f "$SERVICE_PATH" ]]; then
    log_info "Removing unit file: $SERVICE_PATH"
    rm -f "$SERVICE_PATH"
  fi

  log_info "Reloading systemd"
  systemctl daemon-reload
  log_info "Uninstalled ${SERVICE_NAME} and ${TIMER_NAME}"
}

main() {
  require_root

  local action="${1:-}"
  if [[ -z "$action" ]]; then
    usage
    exit 1
  fi
  shift || true

  case "$action" in
    install) install_service "$@" ;;
    uninstall) uninstall_service "$@" ;;
    -h|--help) usage ;;
    *) log_error "Unknown action: $action"; usage; exit 1 ;;
  esac
}

main "$@"
