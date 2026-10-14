#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TARGET=""
SCOPE="user"
DRY_RUN=0

usage() {
  printf '%s\n' "Usage: $0 --target codex|claude|both [--scope user|project] [--dry-run]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target) TARGET=${2:-}; shift 2 ;;
    --scope) SCOPE=${2:-}; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$TARGET" in codex|claude|both) ;; *) usage >&2; exit 2 ;; esac
case "$SCOPE" in user|project) ;; *) usage >&2; exit 2 ;; esac

install_one() {
  platform=$1
  if [ "$SCOPE" = "project" ]; then
    if [ "$platform" = "codex" ]; then dest="$PWD/.agents/skills"; else dest="$PWD/.claude/skills"; fi
  else
    if [ "$platform" = "codex" ]; then dest="${HOME}/.agents/skills"; else dest="${HOME}/.claude/skills"; fi
  fi
  printf 'Target %s: %s\n' "$platform" "$dest"
  [ "$DRY_RUN" -eq 1 ] && return 0
  mkdir -p "$dest"
  for source in "$ROOT"/skills/*; do
    name=$(basename "$source")
    if [ -e "$dest/$name" ]; then
      printf 'Refusing to overwrite existing skill: %s\n' "$dest/$name" >&2
      exit 3
    fi
    cp -R "$source" "$dest/$name"
    printf 'Installed %s\n' "$name"
  done
}

case "$TARGET" in
  codex) install_one codex ;;
  claude) install_one claude ;;
  both) install_one codex; install_one claude ;;
esac
