#!/usr/bin/env bash
set -euo pipefail

TARGET_PATH="/usr/local/bin/pcrt"

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

usage() {
  cat <<'EOF'
Usage:
  pcrt_cli.sh install --project-root <path> --python <python_bin> [--target /usr/local/bin/pcrt]
  pcrt_cli.sh uninstall [--target /usr/local/bin/pcrt]
EOF
}

install_cli() {
  local project_root="" python_bin="" target_path="$TARGET_PATH"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project-root) project_root="$2"; shift 2 ;;
      --python) python_bin="$2"; shift 2 ;;
      --target) target_path="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) log_error "Unknown option: $1"; usage; exit 1 ;;
    esac
  done

  [[ -n "$project_root" ]] || { log_error "--project-root is required"; exit 1; }
  [[ -n "$python_bin" ]] || { log_error "--python is required"; exit 1; }

  project_root="$(abs_path "$project_root")"
  target_path="$(abs_path "$target_path")"

  [[ -d "$project_root" ]] || { log_error "Project root not found: $project_root"; exit 1; }
  [[ -x "$python_bin" ]] || { log_error "Python binary is not executable: $python_bin"; exit 1; }

  mkdir -p "$(dirname "$target_path")"
  log_info "Writing CLI wrapper: $target_path"
  cat >"$target_path" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "${project_root}"
exec "${python_bin}" app/run_ctl.py "\$@"
EOF
  chmod 0755 "$target_path"
  log_info "Installed pcrt wrapper: $target_path"
}

uninstall_cli() {
  local target_path="$TARGET_PATH"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --target) target_path="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) log_error "Unknown option: $1"; usage; exit 1 ;;
    esac
  done

  target_path="$(abs_path "$target_path")"
  if [[ -f "$target_path" ]]; then
    log_info "Removing CLI wrapper: $target_path"
    rm -f "$target_path"
  fi
  log_info "Uninstalled pcrt wrapper"
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
    install) install_cli "$@" ;;
    uninstall) uninstall_cli "$@" ;;
    -h|--help) usage ;;
    *) log_error "Unknown action: $action"; usage; exit 1 ;;
  esac
}

main "$@"
