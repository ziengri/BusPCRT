#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/pcrt}"
DEVICE_ENV_FILE="/etc/pcrt/device.env"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
SYSTEMD_DIR="/etc/systemd/system"

log_info() {
  echo "[INFO] $*"
}

log_warn() {
  echo "[WARN] $*" >&2
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

require_file() {
  local path="$1"
  [[ -f "$path" ]] || { log_error "File not found: $path"; exit 1; }
}

require_executable() {
  local path="$1"
  [[ -x "$path" ]] || { log_error "Executable not found: $path"; exit 1; }
}

if [[ -f "$DEVICE_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$DEVICE_ENV_FILE"
  set +a
fi

NUMBER_CAMS="${NUMBER_CAMS:-3}"
if [[ ! "$NUMBER_CAMS" =~ ^(3|4)$ ]]; then
  echo "[ERROR] NUMBER_CAMS must be 3 or 4, got: $NUMBER_CAMS" >&2
  exit 1
fi

camera_number() {
  local camera_id="$1"
  if [[ "$camera_id" =~ ([0-9]+)$ ]]; then
    echo "${BASH_REMATCH[1]}"
    return 0
  fi
  echo "[ERROR] CAMERA_ID must end with a number when NUMBER_CAMS is used: $camera_id" >&2
  return 1
}

service_script() {
  echo "$PROJECT_ROOT/scripts/services/$1"
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

recorder_instance_from_unit() {
  local unit="$1"
  unit="${unit#buspcrt-recorder@}"
  unit="${unit%.service}"
  [[ -n "$unit" && "$unit" != "buspcrt-recorder@" ]] || return 1
  echo "$unit"
}

uninstall_fixed_services() {
  log_info "Uninstalling fixed BusPCRT services"
  "$(service_script monitor_service.sh)" uninstall
  "$(service_script processor_service.sh)" uninstall
  "$(service_script door_gateway_service.sh)" uninstall
  "$(service_script updater_service.sh)" uninstall
  "$(service_script sessions_cleanup_service.sh)" uninstall
  "$(service_script pcrt_cli.sh)" uninstall
}

collect_recorder_instances() {
  { systemctl list-unit-files 'buspcrt-recorder@*.service' --no-legend --no-pager 2>/dev/null || true; } \
    | awk '{print $1}' \
    | while read -r unit; do recorder_instance_from_unit "$unit" || true; done

  { systemctl list-units --all 'buspcrt-recorder@*.service' --no-legend --no-pager 2>/dev/null || true; } \
    | awk '{print $1}' \
    | while read -r unit; do recorder_instance_from_unit "$unit" || true; done

  { find "$SYSTEMD_DIR" -maxdepth 1 -type d -name 'buspcrt-recorder@*.service.d' 2>/dev/null || true; } \
    | while read -r dropin_dir; do
        local unit
        unit="$(basename "$dropin_dir" .d)"
        recorder_instance_from_unit "$unit" || true
      done
}

uninstall_recorder_services() {
  log_info "Uninstalling existing recorder instances"

  local instances=()
  local instance
  while IFS= read -r instance; do
    [[ -n "$instance" ]] || continue
    instances+=("$instance")
  done < <(collect_recorder_instances | sort -u)

  for instance in "${instances[@]}"; do
    "$(service_script recorder_service.sh)" uninstall --instance "$instance"
  done

  if [[ -f "$SYSTEMD_DIR/buspcrt-recorder@.service" ]]; then
    log_info "Removing recorder template unit: $SYSTEMD_DIR/buspcrt-recorder@.service"
    rm -f "$SYSTEMD_DIR/buspcrt-recorder@.service"
  fi

  systemctl daemon-reload
}

install_fixed_services() {
  log_info "Installing fixed BusPCRT services"
  "$(service_script sessions_cleanup_service.sh)" install --project-root "$PROJECT_ROOT" --env "$PROJECT_ROOT/config.env"
  "$(service_script pcrt_cli.sh)" install --project-root "$PROJECT_ROOT" --python "$PYTHON_BIN"
  "$(service_script door_gateway_service.sh)" install --project-root "$PROJECT_ROOT" --env "$PROJECT_ROOT/door_gateway.env" --python "$PYTHON_BIN"
  "$(service_script processor_service.sh)" install --project-root "$PROJECT_ROOT" --env "$PROJECT_ROOT/processor.env" --python "$PYTHON_BIN"
  "$(service_script monitor_service.sh)" install --project-root "$PROJECT_ROOT" --env "$PROJECT_ROOT/monitor.env" --python "$PYTHON_BIN"
  "$(service_script updater_service.sh)" install --project-root "$PROJECT_ROOT" --env "$PROJECT_ROOT/config.env"
}

install_recorder_services() {
  log_info "Installing recorder services for NUMBER_CAMS=$NUMBER_CAMS"

  local installed=0
  shopt -s nullglob
  for env_file in "$PROJECT_ROOT"/recorder-cam*.env; do
    if ! grep -Eq '^CAMERA_ID=.+$' "$env_file"; then
      continue
    fi
    if ! grep -Eq '^SOURCE=.+$' "$env_file"; then
      continue
    fi
    if ! grep -Eq '^DOOR_CHANNEL=.+$' "$env_file"; then
      continue
    fi

    local camera_id camera_num
    camera_id="$(read_env_value "$env_file" "CAMERA_ID")"
    camera_num="$(camera_number "$camera_id")"
    if (( camera_num > NUMBER_CAMS )); then
      log_info "Skipping inactive camera $camera_id for NUMBER_CAMS=$NUMBER_CAMS"
      continue
    fi

    "$(service_script recorder_service.sh)" install --instance "$camera_id" --project-root "$PROJECT_ROOT" --env "$env_file" --python "$PYTHON_BIN"
    installed=$((installed + 1))
  done
  shopt -u nullglob

  if (( installed == 0 )); then
    log_warn "No recorder services were installed. Check recorder-cam*.env files."
  fi
}

main() {
  require_root
  require_file "$DEVICE_ENV_FILE"
  require_file "$PROJECT_ROOT/config.env"
  require_file "$PROJECT_ROOT/door_gateway.env"
  require_file "$PROJECT_ROOT/processor.env"
  require_file "$PROJECT_ROOT/monitor.env"
  require_executable "$PYTHON_BIN"
  require_executable "$(service_script sessions_cleanup_service.sh)"
  require_executable "$(service_script pcrt_cli.sh)"
  require_executable "$(service_script door_gateway_service.sh)"
  require_executable "$(service_script processor_service.sh)"
  require_executable "$(service_script monitor_service.sh)"
  require_executable "$(service_script updater_service.sh)"
  require_executable "$(service_script recorder_service.sh)"

  log_info "Reinstalling BusPCRT services from $PROJECT_ROOT"
  log_info "Using NUMBER_CAMS=$NUMBER_CAMS from $DEVICE_ENV_FILE"

  uninstall_recorder_services
  uninstall_fixed_services
  install_fixed_services
  install_recorder_services

  log_info "BusPCRT services reinstalled successfully"
}

main "$@"
