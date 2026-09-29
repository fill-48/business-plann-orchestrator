#!/usr/bin/env bash
# Install or uninstall the business-plan-orchestrator skill for Claude Code.
#
#   bash install.sh              install (or update) into ~/.claude/skills/
#   bash install.sh --uninstall  remove the installed skill
#
# An existing installation is backed up to ~/.claude/skill-backups/ before it
# is replaced or removed. Backups live outside ~/.claude/skills/ so Claude Code
# never discovers them as duplicate skills.
set -euo pipefail

name="business-plan-orchestrator"
here="$(cd "$(dirname "$0")" && pwd)"
src="$here/.claude/skills/$name"
dst="$HOME/.claude/skills/$name"
backup_root="$HOME/.claude/skill-backups"

usage() {
  echo "usage: bash install.sh [--uninstall]"
}

backup() {
  if [[ -e "$1" ]]; then
    mkdir -p "$backup_root"
    local base="$backup_root/$name.bak-$(date +%Y%m%d-%H%M%S)"
    local b="$base"
    local n=1
    # Two backups in the same second must not collide (cp -R into an
    # existing directory would nest the copy instead of creating a backup).
    while [[ -e "$b" ]]; do
      b="$base-$n"
      n=$((n + 1))
    done
    cp -R "$1" "$b"
    echo "Backup: $b"
  fi
}

check_prereqs() {
  local py=""
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import sys" >/dev/null 2>&1; then
      py="$candidate"
      break
    fi
  done
  if [[ -z "$py" ]]; then
    echo "WARNING: Python not found. The skill scripts need Python >= 3.12 with the 'jsonschema' package." >&2
    return 0
  fi
  if ! "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >/dev/null 2>&1; then
    echo "WARNING: $("$py" --version 2>&1) found; the skill scripts need Python >= 3.12." >&2
  fi
  if ! "$py" -c "import jsonschema" >/dev/null 2>&1; then
    echo "WARNING: the 'jsonschema' package is missing. Install it with: $py -m pip install -r requirements.txt" >&2
  fi
}

case "${1:-}" in
  "") ;;
  --uninstall)
    backup "$dst"
    rm -rf "$dst"
    echo "Uninstalled."
    exit 0
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

[[ -f "$src/SKILL.md" ]] || { echo "SKILL.md not found in $src" >&2; exit 1; }

mkdir -p "$(dirname "$dst")"
backup "$dst"
rm -rf "$dst"
cp -R "$src" "$dst"
# Local interpreter caches are never part of the package.
find "$dst" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$dst" -name "*.pyc" -type f -delete

[[ -f "$dst/SKILL.md" ]] || { echo "Install verification failed: SKILL.md missing" >&2; exit 1; }
expected=$(cd "$src" && find . -type f ! -path "*/__pycache__/*" ! -name "*.pyc" | wc -l)
actual=$(cd "$dst" && find . -type f | wc -l)
if [[ "$expected" -ne "$actual" ]]; then
  echo "Install verification failed: expected $expected files, found $actual" >&2
  exit 1
fi

echo "Installed to: $dst ($actual files)"
check_prereqs
