#!/bin/bash
# One command install straight from GitHub, for a machine that has nothing on
# it yet:
#
#   curl -fsSL https://raw.githubusercontent.com/mikeneeson/FusionRebuildLLIT/main/bootstrap.sh | sudo bash
#
# Clones the repo to /opt/luckylogic-src and runs the real installer. Safe to
# run again: it updates the clone in place rather than starting over, and the
# installer never overwrites a URL that has already been saved.
set -euo pipefail

REPO="${LUCKYLOGIC_REPO:-https://github.com/mikeneeson/FusionRebuildLLIT.git}"
BRANCH="${LUCKYLOGIC_BRANCH:-main}"
SRC="${LUCKYLOGIC_SRC:-/opt/luckylogic-src}"

[[ $EUID -eq 0 ]] || { echo "Run this as root, for example: curl ... | sudo bash" >&2; exit 1; }

if ! command -v git >/dev/null; then
  echo "== Installing git"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y --no-install-recommends git ca-certificates
fi

if [[ -d "$SRC/.git" ]]; then
  echo "== Updating $SRC"
  git -C "$SRC" remote set-url origin "$REPO"
  git -C "$SRC" fetch --depth 1 origin "$BRANCH"
  # Hard reset rather than pull, so a half finished edit on the box cannot
  # block an update.
  git -C "$SRC" checkout -B "$BRANCH" "origin/$BRANCH"
  git -C "$SRC" reset --hard "origin/$BRANCH"
else
  echo "== Cloning $REPO into $SRC"
  rm -rf "$SRC"
  git clone --depth 1 --branch "$BRANCH" "$REPO" "$SRC"
fi

exec "$SRC/install.sh"
