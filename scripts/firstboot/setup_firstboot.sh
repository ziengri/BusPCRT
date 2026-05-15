#!/usr/bin/env bash
set -Eeuo pipefail

BASE_DIR="/root/firstboot"
PROJECT_ROOT="/opt/pcrt"

DEVICE_TEMPLATE="${BASE_DIR}/device.env"
DEVICE_TARGET="/etc/pcrt/device.env"
INSTALL_SERVICES_SCRIPT="${PROJECT_ROOT}/scripts/services/install_services.sh"

REVERSE_TEMPLATE=""
REVERSE_TARGET="/etc/systemd/system/reverse-tunnel.service"

TUNNEL_KEY="/root/.ssh/id_ed25519_vps_tunnel"
TUNNEL_REMOTE="tunnel@176.57.213.35"

BUS_ID=""
NUMBER_CAMS=""
REVERSE_PORT=""
HOSTNAME_VALUE=""

log_info() {
  echo "[INFO] $*"
}

log_warn() {
  echo "[WARN] $*" >&2
}

log_error() {
  echo "[ERROR] $*" >&2
}

die() {
  log_error "$*"
  exit 1
}

on_error() {
  local line="$1"
  local cmd="$2"
  log_error "Failed at line ${line}: ${cmd}"
  exit 1
}
trap 'on_error "${LINENO}" "${BASH_COMMAND}"' ERR

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    die "Run this script as root."
  fi
}

require_file() {
  local p="$1"
  [[ -f "$p" ]] || die "File not found: $p"
}

require_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || die "Required command not found: $cmd"
}

backup_file() {
  local p="$1"
  local ts
  ts="$(date +%Y%m%d_%H%M%S)"

  if [[ -e "$p" ]]; then
    local backup="${p}.bak.${ts}"
    cp -a "$p" "$backup"
    log_info "Backup created: $backup"
  fi
}

resolve_reverse_template() {
  local candidates=(
    "${BASE_DIR}/reverse-tunnel.service.tpl"
    "${BASE_DIR}/reverse-tunnel.service"
  )

  local p
  for p in "${candidates[@]}"; do
    if [[ -f "$p" ]]; then
      REVERSE_TEMPLATE="$p"
      return 0
    fi
  done

  die "Reverse tunnel template not found. Expected one of: ${candidates[*]}"
}

escape_sed_replacement() {
  printf '%s' "$1" | sed -e 's/[\/&]/\\&/g'
}

letter_to_num() {
  local ch="${1,,}"
  [[ "$ch" =~ ^[a-z]$ ]] || die "Invalid letter: $ch"

  local ascii
  printf -v ascii '%d' "'$ch"
  echo $((ascii - 96))
}

calc_prefix_digit() {
  local bus_id="$1"
  local prefix="${bus_id:0:3}"
  local sum=0
  local i ch

  for ((i=0; i<3; i++)); do
    ch="${prefix:i:1}"
    sum=$((sum + $(letter_to_num "$ch")))
  done

  echo $((sum % 10))
}

calc_reverse_port() {
  local bus_id="$1"
  local digit suffix

  digit="$(calc_prefix_digit "$bus_id")"
  suffix="${bus_id:3:3}"

  echo "2${digit}${suffix}"
}

ask_bus_id() {
  local raw normalized

  while true; do
    read -r -p "Enter bus id (example: mta230): " raw
    normalized="${raw,,}"

    if [[ "$normalized" =~ ^[a-z]{3}[0-9]{3}$ ]]; then
      BUS_ID="$normalized"
      REVERSE_PORT="$(calc_reverse_port "$BUS_ID")"
      HOSTNAME_VALUE="bus-${BUS_ID}"
      return 0
    fi

    log_warn "Invalid format. Use exactly 3 English letters + 3 digits, for example: mta230"
  done
}

ask_number_cams() {
  local raw

  while true; do
    read -r -p "Enter number of cameras (3 or 4): " raw

    if [[ "$raw" =~ ^(3|4)$ ]]; then
      NUMBER_CAMS="$raw"
      return 0
    fi

    log_warn "Invalid camera count. Use 3 or 4."
  done
}

confirm_apply() {
  echo
  echo "Bus ID      : ${BUS_ID}"
  echo "Number cams : ${NUMBER_CAMS}"
  echo "Reverse port: ${REVERSE_PORT}"
  echo "Hostname    : ${HOSTNAME_VALUE}"
  echo

  local answer
  read -r -p "Apply these settings? [y/N]: " answer
  answer="${answer,,}"

  [[ "$answer" =~ ^(y|yes)$ ]] || die "Cancelled by user."
}

cleanup_unique_system_data() {
  log_info "Cleaning unique system identifiers"

  rm -f /etc/machine-id
  rm -f /var/lib/dbus/machine-id || true
  rm -f /etc/ssh/ssh_host_*
  rm -f /var/lib/systemd/random-seed || true
}

regenerate_unique_system_data() {
  log_info "Regenerating machine-id"
  systemd-machine-id-setup >/dev/null

  log_info "Regenerating SSH host keys"
  ssh-keygen -A >/dev/null
}

update_hostname() {
  log_info "Setting hostname to ${HOSTNAME_VALUE}"
  hostnamectl set-hostname "${HOSTNAME_VALUE}"
}

render_device_env() {
  local tmp
  tmp="$(mktemp)"

  sed \
    -e "s/__BUS_ID__/$(escape_sed_replacement "$BUS_ID")/g" \
    -e "s/__REVERSE_PORT__/$(escape_sed_replacement "$REVERSE_PORT")/g" \
    -e "s/__HOSTNAME__/$(escape_sed_replacement "$HOSTNAME_VALUE")/g" \
    -e "s/__NUMBER_CAMS__/$(escape_sed_replacement "$NUMBER_CAMS")/g" \
    "$DEVICE_TEMPLATE" >"$tmp"

  mkdir -p "$(dirname "$DEVICE_TARGET")"
  backup_file "$DEVICE_TARGET"
  install -m 0644 "$tmp" "$DEVICE_TARGET"
  rm -f "$tmp"

  log_info "Written: $DEVICE_TARGET"
}

install_reverse_tunnel_service() {
  local tmp
  tmp="$(mktemp)"

  log_info "Stopping existing reverse-tunnel.service if present"
  systemctl stop reverse-tunnel.service >/dev/null 2>&1 || true
  systemctl disable reverse-tunnel.service >/dev/null 2>&1 || true

  backup_file "$REVERSE_TARGET"

  sed \
    -e "s/__BUS_ID__/$(escape_sed_replacement "$BUS_ID")/g" \
    -e "s/__REVERSE_PORT__/$(escape_sed_replacement "$REVERSE_PORT")/g" \
    -e "s/__HOSTNAME__/$(escape_sed_replacement "$HOSTNAME_VALUE")/g" \
    "$REVERSE_TEMPLATE" >"$tmp"

  install -m 0644 "$tmp" "$REVERSE_TARGET"
  rm -f "$tmp"

  log_info "Reloading systemd"
  systemctl daemon-reload

  log_info "Enabling reverse-tunnel.service"
  systemctl enable reverse-tunnel.service >/dev/null

  log_info "Restarting reverse-tunnel.service"
  systemctl restart reverse-tunnel.service

  if systemctl is-active --quiet reverse-tunnel.service; then
    log_info "reverse-tunnel.service is active"
  else
    log_error "reverse-tunnel.service failed to start"
    systemctl status reverse-tunnel.service --no-pager || true
    journalctl -u reverse-tunnel.service -n 100 --no-pager || true
    exit 1
  fi
}

install_buspcrt_services() {
  log_info "Reinstalling BusPCRT services for NUMBER_CAMS=${NUMBER_CAMS}"

  if ! "$INSTALL_SERVICES_SCRIPT"; then
    log_error "BusPCRT service reinstall failed"
    systemctl status buspcrt-processor.service --no-pager || true
    systemctl status buspcrt-monitor.service --no-pager || true
    systemctl status buspcrt-door-gateway.service --no-pager || true
    systemctl status buspcrt-updater.timer --no-pager || true
    journalctl -u buspcrt-monitor.service -n 100 --no-pager || true
    exit 1
  fi

  log_info "BusPCRT services reinstalled for NUMBER_CAMS=${NUMBER_CAMS}"
}

main() {
  require_root

  require_cmd sed
  require_cmd install
  require_cmd systemctl
  require_cmd hostnamectl
  require_cmd systemd-machine-id-setup
  require_cmd ssh-keygen

  require_file "$DEVICE_TEMPLATE"
  resolve_reverse_template
  require_file "$REVERSE_TEMPLATE"
  require_file "$INSTALL_SERVICES_SCRIPT"
  [[ -f "$TUNNEL_KEY" ]] || die "Tunnel SSH key not found: $TUNNEL_KEY"

  ask_bus_id
  ask_number_cams
  confirm_apply

  cleanup_unique_system_data
  regenerate_unique_system_data
  update_hostname
  render_device_env
  install_reverse_tunnel_service
  install_buspcrt_services

  echo
  log_info "Done."
  echo "BUS_ID=${BUS_ID}"
  echo "NUMBER_CAMS=${NUMBER_CAMS}"
  echo "REVERSE_PORT=${REVERSE_PORT}"
  echo "HOSTNAME=${HOSTNAME_VALUE}"
  echo "DEVICE_ENV=${DEVICE_TARGET}"
  echo "SERVICE=${REVERSE_TARGET}"
  echo "PROJECT_ROOT=${PROJECT_ROOT}"
  echo "BUSPCRT_SERVICES=reinstalled"
}

main "$@"
