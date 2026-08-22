#!/bin/bash
# LuckyLogic Player installer.
#
#   sudo ./install.sh
#
# Turns a bare Debian 13 machine with no desktop into a signage player. Safe to
# run again at any time: re-running is how updates are applied, and it never
# touches a URL that has already been saved.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SHARE=/opt/luckylogic          # the code, root owned
STATE=/var/lib/luckylogic      # config and browser profile, player owned
ETC=/etc/luckylogic            # installer bookkeeping
PLAYER=player

say() { printf '\n== %s\n' "$1"; }

[[ $EUID -eq 0 ]] || { echo "Run this with sudo: sudo ./install.sh" >&2; exit 1; }

# Built and tested on Debian 13. It will probably work elsewhere, but on Ubuntu
# the chromium package is a snap wrapper that cannot run under cage, so warn.
if ! grep -qi debian /etc/os-release 2>/dev/null; then
  echo "Warning: this is built for Debian 13. Chromium may not work here." >&2
fi


say "Installing packages"
# cage is the entire graphics stack: a Wayland compositor that runs exactly one
# fullscreen program and nothing else. grim takes screenshots of it, wayvnc
# shares it over the network, va-driver-all is Intel hardware video decode.
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  cage \
  chromium \
  curl \
  fonts-dejavu-core \
  grim \
  iproute2 \
  python3 \
  sudo \
  va-driver-all \
  vainfo \
  wayvnc


say "Creating the player user"
# A locked system account with no password and no login shell. It owns the
# screen and nothing else on the machine.
if ! id -u "$PLAYER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$STATE" \
          --shell /usr/sbin/nologin "$PLAYER"
fi
# video and render are for the GPU, input is for the air remote.
for group in video render input; do
  getent group "$group" >/dev/null && usermod -aG "$group" "$PLAYER"
done


say "Installing the code to $SHARE"
rm -rf "$SHARE"
mkdir -p "$SHARE"
cp -r "$SRC/player/bin" "$SRC/player/setup" "$SHARE/"
chmod 755 "$SHARE/bin/"*
find "$SHARE" -type d -exec chmod 755 {} +

# One word commands, on the path for whoever is logged in.
ln -sf "$SHARE/bin/luckylogic-shot"   /usr/local/bin/luckylogic-shot
ln -sf "$SHARE/bin/luckylogic-update" /usr/local/bin/luckylogic-update
ln -sf "$SHARE/bin/luckylogic-vnc"    /usr/local/bin/luckylogic-vnc


say "Setting up $STATE"
# Everything the kiosk reads has to be readable by the unprivileged player
# user, which is why none of this can live on the EFI partition.
mkdir -p "$STATE/chromium"
if [[ ! -f "$STATE/player.conf" ]]; then
  cp "$SRC/player/config/player.conf.default" "$STATE/player.conf"
  echo "Wrote a fresh config. This player has no URL yet."
else
  echo "Keeping the existing config at $STATE/player.conf"
fi
chown -R "$PLAYER:$PLAYER" "$STATE"
chmod 755 "$STATE"
chmod 644 "$STATE/player.conf"


say "Installing the Chromium policy"
# This plus the "First Run" marker the kiosk writes is what stops the
# terms-of-service dialog appearing over the top of the page on a fresh box.
mkdir -p /etc/chromium/policies/managed
install -m 644 "$SRC/player/chromium/policies.json" \
  /etc/chromium/policies/managed/luckylogic.json


say "Turning off the tty1 login prompt"
# Otherwise the login prompt and the kiosk fight over the console and the
# screen flickers between the two.
systemctl disable --now getty@tty1.service >/dev/null 2>&1 || true
systemctl mask getty@tty1.service >/dev/null 2>&1 || true


say "Installing the services"
for unit in luckylogic-kiosk luckylogic-vnc; do
  install -m 644 "$SRC/player/systemd/$unit.service" "/etc/systemd/system/$unit.service"
done
systemctl daemon-reload
systemctl enable luckylogic-kiosk.service >/dev/null
# Live view runs all the time but sits idle unless VNC="on" in the config, so
# turning it on later never needs a service restart or a reboot.
systemctl enable luckylogic-vnc.service >/dev/null

# No desktop is installed, so make sure the machine boots to a plain console
# and lets the kiosk service take the screen.
systemctl set-default multi-user.target >/dev/null 2>&1 || true

# Remember where this copy of the repo lives so luckylogic-update can find it.
mkdir -p "$ETC"
printf '%s\n' "$SRC" > "$ETC/install-source"


say "Starting the kiosk"
systemctl restart luckylogic-kiosk.service
systemctl restart luckylogic-vnc.service

cat <<SUMMARY

LuckyLogic Player is installed.

  What is on the TV now   $(grep -q '^URL=""' "$STATE/player.conf" && echo "the setup holding screen" || echo "the saved page")
  This machine            $(hostname -I | awk '{print $1}')
  Config                  $STATE/player.conf
  Check it is running     systemctl status luckylogic-kiosk
  Watch what it is doing  journalctl -u luckylogic-kiosk -f
  Screenshot the TV       sudo luckylogic-shot
  Watch it live           sudo luckylogic-vnc on
  Update later            sudo luckylogic-update

SUMMARY
