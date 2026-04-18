#!/usr/bin/env bash
set -euo pipefail

log_info() {
  echo "[INFO] $*"
}

log_error() {
  echo "[ERROR] $*" >&2
}

usage() {
  cat <<'EOF'
Usage:
  cleanup_sessions.sh [--config-env-file <path>]
EOF
}

abs_path() {
  local p="$1"
  if command -v realpath >/dev/null 2>&1; then
    realpath -m "$p"
  else
    readlink -m "$p"
  fi
}

read_env_value() {
  local env_file="$1"
  local key="$2"
  awk -F= -v key="$key" '
    $0 ~ "^[[:space:]]*"key"=" {
      sub(/^[^=]*=/, "", $0)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0)
      gsub(/^["'\'']|["'\'']$/, "", $0)
      print $0
      exit
    }
  ' "$env_file"
}

is_protected_path() {
  local p="$1"
  case "$p" in
    "/"|"/boot"|"/dev"|"/etc"|"/home"|"/opt"|"/proc"|"/root"|"/run"|"/srv"|"/sys"|"/tmp"|"/usr"|"/var")
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

cleanup_dir_contents() {
  local dir="$1"
  mkdir -p "$dir"
  find "$dir" -mindepth 1 -exec rm -rf -- {} +
}

main() {
  local config_env_file="config.env"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --config-env-file) config_env_file="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) log_error "Unknown option: $1"; usage; exit 1 ;;
    esac
  done

  config_env_file="$(abs_path "$config_env_file")"
  [[ -f "$config_env_file" ]] || { log_error "Env file not found: $config_env_file"; exit 1; }

  local sessions_dir
  sessions_dir="$(read_env_value "$config_env_file" "SESSIONS_DIR")"
  [[ -n "$sessions_dir" ]] || { log_error "SESSIONS_DIR is empty in $config_env_file"; exit 1; }

  local sessions_root
  sessions_root="$(abs_path "$sessions_dir")"
  if is_protected_path "$sessions_root"; then
    log_error "Refusing to use protected path for SESSIONS_DIR: $sessions_root"
    exit 1
  fi

  local active_dir processing_dir
  active_dir="${sessions_root}/active"
  processing_dir="${sessions_root}/processing"

  log_info "Cleaning session directories:"
  log_info "  active: ${active_dir}"
  log_info "  processing: ${processing_dir}"

  cleanup_dir_contents "$active_dir"
  cleanup_dir_contents "$processing_dir"
  log_info "Cleanup completed"
}

main "$@"
