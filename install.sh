#!/bin/bash
# LuckyLogic Player installer.
#
#   curl -sSL https://central.luckylogic.com.au/player/install.sh | sudo bash
#
# Takes a fresh Debian 13 (Trixie) minimal install to a working signage
# player. Idempotent: re-running it is how updates are applied. A saved
# controller URL is never touched.
#
# Two modes, decided by the VERSION stamp below:
#   dev       Run from a git checkout: installs the working tree directly.
#   x.y.z     The released copy (stamped by release.sh): downloads the
#             matching tarball from central, verifies its sha256, installs.
set -euo pipefail

VERSION="dev"
SHA256="unstamped"
CENTRAL_URL="https://central.luckylogic.com.au/player"

say()  { echo -e "\e[32m==>\e[0m $*"; }
die()  { echo -e "\e[31merror:\e[0m $*" >&2; exit 1; }

# ------------------------------------------------------------- guards

[ "$(id -u)" -eq 0 ] || die "run as root: curl -sSL .../install.sh | sudo bash"

[ "$(uname -m)" = "x86_64" ] || die "this player targets x86_64 mini PCs"

if [ -r /etc/os-release ]; then
    # shellcheck source=/dev/null
    . /etc/os-release
else
    die "cannot read /etc/os-release"
fi
if [ "${ID:-}" != "debian" ] || [ "${VERSION_ID:-}" != "13" ]; then
    if [ "${LL_SKIP_OS_CHECK:-0}" != "1" ]; then
        die "expected Debian 13 (Trixie), found ${ID:-?} ${VERSION_ID:-?}. Set LL_SKIP_OS_CHECK=1 to override."
    fi
    say "OS check overridden (found ${ID:-?} ${VERSION_ID:-?})"
fi

# ------------------------------------------------- locate the payload

TMP=""
cleanup() { [ -n "$TMP" ] && rm -rf "$TMP"; }
trap cleanup EXIT

if [ "$VERSION" = "dev" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd)" \
        || SCRIPT_DIR=""
    if [ -z "$SCRIPT_DIR" ] || [ ! -d "$SCRIPT_DIR/player" ]; then
        die "dev install needs a repo checkout next to this script. For real installs use the released install.sh from central."
    fi
    PAYLOAD="$SCRIPT_DIR/player"
    say "Installing from working tree: $PAYLOAD"
else
    TMP="$(mktemp -d)"
    TARBALL="luckylogic-player-$VERSION.tar.gz"
    say "Downloading $TARBALL"
    curl -fsSL "$CENTRAL_URL/$TARBALL" -o "$TMP/$TARBALL"
    say "Verifying checksum"
    echo "$SHA256  $TMP/$TARBALL" | sha256sum -c - >/dev/null \
        || die "checksum mismatch on $TARBALL. Refusing to install."
    tar -xzf "$TMP/$TARBALL" -C "$TMP"
    PAYLOAD="$TMP/player"
    [ -d "$PAYLOAD" ] || die "tarball did not contain a player/ directory"
fi

# ----------------------------------------------------------- packages

say "Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq cage chromium grim python3 curl ca-certificates

# --------------------------------------------------------- player user

if ! id player >/dev/null 2>&1; then
    say "Creating the 'player' user"
    useradd --create-home --shell /bin/bash \
            --groups video,render,input player
else
    usermod -aG video,render,input player
fi

# ---------------------------------------------------------- state dir

# /var/lib/luckylogic holds the controller URL, the installed version and
# the Chromium profile. Owned by 'player' so the unprivileged setup server
# can write the URL. Never wiped: the URL survives updates.
install -d -o player -g player /var/lib/luckylogic
install -d -o player -g player /var/lib/luckylogic/chromium

# ------------------------------------------------------------- payload

say "Installing player files to /opt/luckylogic"
rm -rf /opt/luckylogic
mkdir -p /opt/luckylogic
cp -a "$PAYLOAD/." /opt/luckylogic/
chmod 755 /opt/luckylogic/bin/*
ln -sf /opt/luckylogic/bin/luckylogic-screenshot /usr/local/bin/luckylogic-screenshot
ln -sf /opt/luckylogic/bin/luckylogic-update     /usr/local/bin/luckylogic-update

say "Installing Chromium managed policy"
install -D -m 644 "$PAYLOAD/chromium/policies.json" \
    /etc/chromium/policies/managed/luckylogic.json

say "Installing sudoers rule (kiosk restart only)"
install -m 440 "$PAYLOAD/system/sudoers" /etc/sudoers.d/luckylogic
visudo -cf /etc/sudoers.d/luckylogic >/dev/null \
    || die "sudoers file failed validation"

say "Arming the hardware watchdog"
install -D -m 644 "$PAYLOAD/system/watchdog.conf" \
    /etc/systemd/system.conf.d/luckylogic-watchdog.conf

say "Installing systemd units"
cp "$PAYLOAD"/systemd/luckylogic-*.service /etc/systemd/system/
cp "$PAYLOAD"/systemd/luckylogic-*.timer   /etc/systemd/system/

# -------------------------------------------------------- system state

# The getty on tty1 fights cage for the console and, combined with TTY
# reset options, caused a restart loop. It stays off, permanently.
say "Disabling getty on tty1"
systemctl disable --now getty@tty1.service >/dev/null 2>&1 || true
systemctl mask getty@tty1.service >/dev/null

systemctl set-default multi-user.target >/dev/null

say "Enabling and starting services"
systemctl daemon-reexec   # picks up the watchdog config
systemctl daemon-reload
systemctl enable luckylogic-setup.service luckylogic-kiosk.service \
                 luckylogic-nightly.timer >/dev/null
systemctl restart luckylogic-setup.service
systemctl restart luckylogic-kiosk.service
systemctl start luckylogic-nightly.timer

echo "$VERSION" > /var/lib/luckylogic/version
chown player:player /var/lib/luckylogic/version

# -------------------------------------------------------------- summary

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
URL="$(cat /var/lib/luckylogic/url 2>/dev/null || true)"

echo
say "LuckyLogic Player $VERSION installed."
if [ -n "$URL" ]; then
    echo "    Controller URL:  $URL"
else
    echo "    Controller URL:  not set. The TV is showing the setup screen."
    echo "    Configure from a phone:  http://${IP:-<player-ip>}:8080/setup"
fi
echo "    Change URL later:   http://${IP:-<player-ip>}:8080/setup"
echo "    Check the screen:   sudo luckylogic-screenshot > screen.png"
echo "    Check for updates:  sudo luckylogic-update"
echo
echo "    One manual step per box: in the BIOS, set 'Power On after AC Loss'"
echo "    so the player recovers from power cuts without a button press."
