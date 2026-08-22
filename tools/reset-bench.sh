#!/bin/bash
# Reset a LuckyLogic bench machine to a clean base, over SSH, without
# losing SSH. Use this between test runs of install.sh.
#
#   sudo ./reset-bench.sh                 full reset (asks before purging)
#   sudo ./reset-bench.sh --player-only   only undo install.sh
#   sudo ./reset-bench.sh --dry-run       print the plan, change nothing
#   sudo ./reset-bench.sh --yes           no prompts
#
# Never touches: openssh-server, network configuration, your own account,
# sudo. Re-enables the tty1 console login that install.sh masks, so a
# broken SSH setup cannot lock you out of the box.
#
# This is not a reinstall. It reverts the player and the usual kiosk
# experiment packages. For a truly pristine Debian you need to reimage,
# which needs physical access.
set -euo pipefail

DRY_RUN=0
ASSUME_YES=0
PLAYER_ONLY=0

for arg in "$@"; do
    case "$arg" in
        --dry-run)     DRY_RUN=1 ;;
        --yes|-y)      ASSUME_YES=1 ;;
        --player-only) PLAYER_ONLY=1 ;;
        -h|--help)     sed -n '2,17p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 1 ;;
    esac
done

say()  { echo -e "\e[32m==>\e[0m $*"; }
warn() { echo -e "\e[33mwarning:\e[0m $*" >&2; }
die()  { echo -e "\e[31merror:\e[0m $*" >&2; exit 1; }

run() {
    if [ "$DRY_RUN" = 1 ]; then
        echo "      would run: $*"
    else
        "$@"
    fi
}

# Same, but for steps that are noisy or allowed to fail. Keeps the dry-run
# plan complete: never redirect a run/qrun call at the call site, or the
# plan line disappears along with the output.
qrun() {
    if [ "$DRY_RUN" = 1 ]; then
        echo "      would run: $*"
    else
        "$@" >/dev/null 2>&1 || true
    fi
}

installed() {
    dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q '^install ok installed'
}

# ------------------------------------------------------------- guards

[ "$(id -u)" -eq 0 ] || die "run with sudo"

# If SSH is not actually serving this box, the promise in the header is
# void and a purge could strand the machine.
if ! installed openssh-server; then
    die "openssh-server is not installed. Refusing to run: this script's whole premise is that SSH survives."
fi
if ! systemctl is-active --quiet ssh && ! systemctl is-active --quiet sshd; then
    die "the SSH server is not running. Fix that before wiping anything."
fi

ADMIN="${SUDO_USER:-root}"
if [ "$ADMIN" = "player" ]; then
    die "refusing to run as the 'player' user, which this script deletes"
fi

if [ "$DRY_RUN" = 1 ]; then
    say "DRY RUN. Nothing will be changed."
fi
say "Protected: openssh-server, networking, sudo, and the '$ADMIN' account."

# -------------------------------------------- stop and remove the player

say "Stopping LuckyLogic services"
for unit in luckylogic-kiosk.service luckylogic-setup.service \
            luckylogic-nightly.timer luckylogic-nightly.service; do
    if systemctl cat "$unit" >/dev/null 2>&1; then
        qrun systemctl disable --now "$unit"
    fi
done

# Do this early and unconditionally. A masked getty means no console
# login, so if anything below breaks SSH the box would need a keyboard.
say "Restoring console login on tty1"
qrun systemctl unmask getty@tty1.service
qrun systemctl enable --now getty@tty1.service

# Disarm the hardware watchdog before we start pulling packages, so a slow
# apt transaction can never trip a 30 second reset.
if [ -f /etc/systemd/system.conf.d/luckylogic-watchdog.conf ]; then
    say "Disarming the hardware watchdog"
    run rm -f /etc/systemd/system.conf.d/luckylogic-watchdog.conf
    run systemctl daemon-reexec
fi

say "Removing LuckyLogic files"
run rm -rf /opt/luckylogic
run rm -rf /var/lib/luckylogic
run rm -f  /etc/sudoers.d/luckylogic
run rm -f  /etc/chromium/policies/managed/luckylogic.json
run rm -f  /usr/local/bin/luckylogic-screenshot
run rm -f  /usr/local/bin/luckylogic-update
run rm -f  /etc/systemd/system/luckylogic-kiosk.service
run rm -f  /etc/systemd/system/luckylogic-setup.service
run rm -f  /etc/systemd/system/luckylogic-nightly.service
run rm -f  /etc/systemd/system/luckylogic-nightly.timer
run systemctl daemon-reload

if id player >/dev/null 2>&1; then
    say "Removing the 'player' user and its home directory"
    qrun loginctl terminate-user player
    if [ "$DRY_RUN" = 1 ]; then
        echo "      would run: userdel -r player"
    elif ! userdel -r player >/dev/null 2>&1; then
        warn "userdel reported an issue; check /home for a leftover directory"
    fi
fi

# ---------------------------------------------------------- package purge

PLAYER_PKGS="cage chromium chromium-common chromium-sandbox grim seatd"

# Things a kiosk experiment tends to leave behind. Purged only if present,
# and only in a full reset.
EXPERIMENT_PKGS="xserver-xorg xserver-xorg-core xserver-xorg-legacy xinit \
x11-xserver-utils xwayland lightdm gdm3 sddm greetd nodm \
openbox i3 matchbox-window-manager fluxbox icewm \
weston sway wayfire cog kiosk-browser \
unclutter xdotool wmctrl \
firefox-esr epiphany-browser \
task-gnome-desktop task-xfce-desktop task-lxde-desktop \
gnome-core xfce4 lxde plasma-desktop"

CANDIDATES="$PLAYER_PKGS"
[ "$PLAYER_ONLY" = 0 ] && CANDIDATES="$PLAYER_PKGS $EXPERIMENT_PKGS"

PURGE=""
for p in $CANDIDATES; do
    if installed "$p"; then
        PURGE="$PURGE $p"
    fi
done
PURGE="${PURGE# }"

if [ -z "$PURGE" ]; then
    say "No player or kiosk packages installed. Nothing to purge."
else
    say "Packages to purge:"
    echo "$PURGE" | tr ' ' '\n' | sed 's/^/      /'

    # Belt and braces: make sure nothing essential can be swept up by the
    # autoremove that follows.
    for keep in openssh-server sudo systemd ifupdown network-manager \
                systemd-resolved python3 curl ca-certificates; do
        if installed "$keep"; then
            qrun apt-mark manual "$keep"
        fi
    done

    if [ "$ASSUME_YES" = 0 ] && [ "$DRY_RUN" = 0 ]; then
        read -r -p "Purge these and autoremove their dependencies? [y/N] " reply
        case "$reply" in
            [yY]*) ;;
            *) die "aborted by user; nothing purged (files above were already removed)" ;;
        esac
    fi

    export DEBIAN_FRONTEND=noninteractive
    # shellcheck disable=SC2086
    run apt-get purge -y $PURGE
    run apt-get autoremove --purge -y
    run apt-get clean
fi

run rm -rf /etc/chromium /etc/chromium-browser

# ------------------------------------------------------------- tidy up

say "Clearing old journal logs so the next test run starts clean"
qrun journalctl --rotate
qrun journalctl --vacuum-time=1s

qrun systemctl set-default multi-user.target

# ------------------------------------------------------------- report

echo
if [ "$DRY_RUN" = 1 ]; then
    say "Dry run complete. Nothing was changed."
    exit 0
fi

say "Reset complete."
echo
printf '    %-22s %s\n' "SSH server:" \
    "$(systemctl is-active ssh 2>/dev/null || systemctl is-active sshd 2>/dev/null || echo unknown)"
printf '    %-22s %s\n' "Console on tty1:" \
    "$(systemctl is-enabled getty@tty1.service 2>/dev/null || echo unknown)"
printf '    %-22s %s\n' "'player' user:" \
    "$(id player >/dev/null 2>&1 && echo 'still present' || echo removed)"

leftovers="$(ls -d /opt/luckylogic /var/lib/luckylogic 2>/dev/null || true)"
printf '    %-22s %s\n' "LuckyLogic files:" \
    "${leftovers:-none}"
printf '    %-22s %s\n' "Root filesystem:" \
    "$(df -h / | awk 'NR==2 {print $4" free of "$2}')"

echo
warn "Do not close this SSH session yet."
echo "    Open a second terminal and confirm you can still log in:"
echo "        ssh ${ADMIN}@$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "    Only once that works should you close this one."
