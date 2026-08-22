#!/bin/bash
# Package a player release, ready to upload to central.
#
#   ./release.sh 1.0.0
#
# Produces in dist/:
#   luckylogic-player-1.0.0.tar.gz   the payload (player/ + install.sh)
#   luckylogic-player-1.0.0.sha256   checksum, for manual verification
#   install.sh                       stamped with VERSION and SHA256
#
# Upload all three to https://central.luckylogic.com.au/player/ so that
# .../player/install.sh always points at the newest release. Keep old
# tarballs around: their stamped installers keep working.
set -euo pipefail

VER="${1:-}"
[[ "$VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
    || { echo "usage: ./release.sh <version, e.g. 1.0.0>" >&2; exit 1; }

cd "$(dirname "$0")"
[ -d player ] && [ -f install.sh ] || { echo "run from the repo root" >&2; exit 1; }

if ! git diff --quiet HEAD -- player install.sh 2>/dev/null; then
    echo "warning: uncommitted changes in player/ or install.sh are going into this release" >&2
fi

mkdir -p dist
TARBALL="dist/luckylogic-player-$VER.tar.gz"

tar -czf "$TARBALL" --exclude='__pycache__' player install.sh
SHA="$(sha256sum "$TARBALL" | awk '{print $1}')"
echo "$SHA  luckylogic-player-$VER.tar.gz" > "dist/luckylogic-player-$VER.sha256"

sed -e "s|^VERSION=\"dev\"|VERSION=\"$VER\"|" \
    -e "s|^SHA256=\"unstamped\"|SHA256=\"$SHA\"|" \
    install.sh > dist/install.sh
chmod 755 dist/install.sh

grep -q "^VERSION=\"$VER\"" dist/install.sh || { echo "stamping failed" >&2; exit 1; }

echo "Release $VER packaged:"
echo "    $TARBALL"
echo "    dist/luckylogic-player-$VER.sha256"
echo "    dist/install.sh   (stamped: VERSION=$VER)"
echo
echo "Upload the three files to https://central.luckylogic.com.au/player/"
echo "Then tag it:  git tag v$VER && git push origin v$VER"
