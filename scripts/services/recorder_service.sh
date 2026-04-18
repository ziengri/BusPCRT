#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_UNIT_NAME="buspcrt-recorder@.service"
TEMPLATE_UNIT_PATH="/etc/systemd/system/${TEMPLATE_UNIT_NAME}"
INSTANCE_PREFIX="buspcrt-recorder@"

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

instance_unit_name() {
  local instance="$1"
  echo "${INSTANCE_PREFIX}${instance}.service"
}

instance_dropin_dir() {
  local instance="$1"
  echo "/etc/systemd/system/${INSTANCE_PREFIX}${instance}.service.d"
}

usage() {
  cat <<'EOF'
Usage:
  recorder_service.sh install --instance <name> --project-root <path> --env <recorder_X.env> --python <python_bin>
  recorder_service.sh uninstall --instance <name>
EOF
}

write_template_unit() {
  log_info "Writing template unit: $TEMPLATE_UNIT_PATH"
  cat >"$TEMPLATE_UNIT_PATH" <<'EOF'
[Unit]
Description=BusPCRT Recorder Service (%i)
After=network.target buspcrt-sessions-cleanup.service

[Service]
Type=simple
User=root
Group=root
ExecStart=/bin/false
Restart=always
RestartSec=1
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
}

write_instance_override() {
  local instance="$1" project_root="$2" env_file="$3" python_bin="$4"
  local dropin_dir
  dropin_dir="$(instance_dropin_dir "$instance")"
  mkdir -p "$dropin_dir"

  log_info "Writing override for instance '${instance}'"
  cat >"${dropin_dir}/override.conf" <<EOF
[Service]
WorkingDirectory=${project_root}
EnvironmentFile=${env_file}
ExecStart=
ExecStart=${python_bin} app/run_recorder.py --env-file ${env_file}
EOF
}

install_service() {
  local instance="" project_root="" env_file="" python_bin=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --instance) instance="$2"; shift 2 ;;
      --project-root) project_root="$2"; shift 2 ;;
      --env) env_file="$2"; shift 2 ;;
      --python) python_bin="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) log_error "Unknown option: $1"; usage; exit 1 ;;
    esac
  done

  [[ -n "$instance" ]] || { log_error "--instance is required"; exit 1; }
  [[ -n "$project_root" ]] || { log_error "--project-root is required"; exit 1; }
  [[ -n "$env_file" ]] || { log_error "--env is required"; exit 1; }
  [[ -n "$python_bin" ]] || { log_error "--python is required"; exit 1; }

  project_root="$(abs_path "$project_root")"
  env_file="$(abs_path "$env_file")"
  # python_bin="$(abs_path "$python_bin")"

  [[ -d "$project_root" ]] || { log_error "Project root not found: $project_root"; exit 1; }
  [[ -f "$env_file" ]] || { log_error "Env file not found: $env_file"; exit 1; }
  [[ -x "$python_bin" ]] || { log_error "Python binary is not executable: $python_bin"; exit 1; }

  write_template_unit
  write_instance_override "$instance" "$project_root" "$env_file" "$python_bin"

  local unit
  unit="$(instance_unit_name "$instance")"

  log_info "Reloading systemd"
  systemctl daemon-reload
  log_info "Enabling and starting ${unit}"
  systemctl enable --now "$unit"
  log_info "Done. Check: systemctl status ${unit}"
}

uninstall_service() {
  local instance=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --instance) instance="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) log_error "Unknown option: $1"; usage; exit 1 ;;
    esac
  done

  [[ -n "$instance" ]] || { log_error "--instance is required for uninstall"; exit 1; }
  local unit
  unit="$(instance_unit_name "$instance")"

  log_info "Stopping and disabling ${unit} (if exists)"
  systemctl disable --now "$unit" >/dev/null 2>&1 || true

  local dropin_dir
  dropin_dir="$(instance_dropin_dir "$instance")"
  if [[ -d "$dropin_dir" ]]; then
    log_info "Removing instance override: $dropin_dir"
    rm -rf "$dropin_dir"
  fi

  log_info "Reloading systemd"
  systemctl daemon-reload
  log_info "Uninstalled instance ${unit}"
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
