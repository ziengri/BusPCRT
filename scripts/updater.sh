#!/usr/bin/env bash
set -Eeuo pipefail

log_info() {
  echo "[INFO] $*"
}

log_warn() {
  echo "[WARN] $*" >&2
}

log_error() {
  echo "[ERROR] $*" >&2
}

require_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || {
    log_error "Required command not found: $cmd"
    exit 1
  }
}

load_env_file() {
  local path="$1"
  [[ -f "$path" ]] || return 0
  set -a
  # shellcheck disable=SC1090
  source "$path"
  set +a
}

abs_path() {
  local p="$1"
  if command -v realpath >/dev/null 2>&1; then
    realpath "$p"
  else
    readlink -f "$p"
  fi
}

usage() {
  cat <<'EOF'
Usage:
  updater.sh [--config-env-file <path>] [--updater-env-file <path>]
EOF
}

parse_args() {
  CONFIG_ENV_FILE="config.env"
  UPDATER_ENV_FILE="updater.env"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --config-env-file) CONFIG_ENV_FILE="$2"; shift 2 ;;
      --updater-env-file) UPDATER_ENV_FILE="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) log_error "Unknown option: $1"; usage; exit 1 ;;
    esac
  done
}

unit_exists() {
  local unit="$1"
  systemctl list-unit-files "$unit" --no-legend --no-pager 2>/dev/null | awk '{print $1}' | grep -Fxq "$unit"
}

discover_units() {
  local unit

  for unit in buspcrt-door-gateway.service buspcrt-processor.service; do
    if unit_exists "$unit"; then
      echo "$unit"
    else
      log_warn "Unit not installed, skip restart: $unit"
    fi
  done

  systemctl list-unit-files 'buspcrt-recorder@*.service' --no-legend --no-pager 2>/dev/null \
    | awk '{print $1}' \
    | grep -E '^buspcrt-recorder@.+\.service$' \
    | grep -v '^buspcrt-recorder@\.service$' \
    | sort -u || true
}

restore_units_state() {
  local snapshot_file="$1"
  local unit was_active
  while IFS='|' read -r unit was_active; do
    [[ -n "$unit" ]] || continue
    if [[ "$was_active" == "1" ]]; then
      systemctl start "$unit" >/dev/null 2>&1 || true
    else
      systemctl stop "$unit" >/dev/null 2>&1 || true
    fi
  done <"$snapshot_file"
}

restart_units_with_recovery() {
  local snapshot_file
  snapshot_file="$(mktemp)"

  local -a units=()
  mapfile -t units < <(discover_units)

  if [[ "${#units[@]}" -eq 0 ]]; then
    log_warn "No BusPCRT units found for restart"
    rm -f "$snapshot_file"
    return 0
  fi

  local unit
  for unit in "${units[@]}"; do
    if systemctl is-active --quiet "$unit"; then
      echo "${unit}|1" >>"$snapshot_file"
    else
      echo "${unit}|0" >>"$snapshot_file"
    fi
  done

  for unit in "${units[@]}"; do
    log_info "Restarting: $unit"
    if ! systemctl restart "$unit"; then
      log_error "Restart failed for $unit, restoring previous states"
      restore_units_state "$snapshot_file"
      rm -f "$snapshot_file"
      return 1
    fi
  done

  rm -f "$snapshot_file"
  return 0
}

main() {
  parse_args "$@"

  require_cmd git
  require_cmd systemctl
  require_cmd flock

  local lock_file="/run/buspcrt-updater.lock"
  mkdir -p "$(dirname "$lock_file")"

  exec 9>"$lock_file"
  if ! flock -n 9; then
    log_warn "Updater is already running; exit"
    exit 0
  fi

  CONFIG_ENV_FILE="$(abs_path "$CONFIG_ENV_FILE")"
  UPDATER_ENV_FILE="$(abs_path "$UPDATER_ENV_FILE")"

  load_env_file "$CONFIG_ENV_FILE"
  load_env_file "$UPDATER_ENV_FILE"

  local update_enabled="${UPDATE_ENABLED:-1}"
  local update_remote="${UPDATE_REMOTE:-origin}"
  local update_branch="${UPDATE_BRANCH:-main}"

  if [[ "$update_enabled" != "1" ]]; then
    log_info "UPDATE_ENABLED=${update_enabled}; updater disabled"
    exit 0
  fi

  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
    log_error "Current directory is not a git repository"
    exit 1
  }

  git remote get-url "$update_remote" >/dev/null 2>&1 || {
    log_error "Git remote not found: $update_remote"
    exit 1
  }

  log_info "Checking updates: remote=${update_remote} branch=${update_branch}"
  git fetch --prune "$update_remote"

  local local_head remote_head
  local_head="$(git rev-parse HEAD)"
  remote_head="$(git rev-parse "${update_remote}/${update_branch}" 2>/dev/null)" || {
    log_error "Remote branch not found: ${update_remote}/${update_branch}"
    exit 1
  }

  if [[ "$local_head" == "$remote_head" ]]; then
    log_info "No updates found"
    exit 0
  fi

  log_info "Update found: ${local_head} -> ${remote_head}"
  git reset --hard HEAD
  git pull --ff-only "$update_remote" "$update_branch"

  restart_units_with_recovery
  log_info "Update applied successfully"
}

main "$@"
