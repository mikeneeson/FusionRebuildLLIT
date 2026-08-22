#!/bin/bash
# Launched by luckylogic-kiosk.service. Starts cage with a single Chromium
# window pointed at the local setup server, which serves either the setup
# page (no URL configured) or a splash that forwards to the controller.
#
# Chromium always starts at 127.0.0.1:8080 rather than the controller URL
# directly so that boot ordering never matters: after a power cut the NAS
# can take minutes longer than the player to come up, and the splash page
# polls until the controller answers.
set -u

PROFILE_DIR=/var/lib/luckylogic/chromium

# If Chromium was killed hard (crash, OOM, power cut) it records an unclean
# exit and would offer a "Restore pages?" bar. Rewrite the flags before every
# launch. --disable-session-crashed-bubble covers this too; both together is
# the combination that has proven reliable on kiosks.
PREFS="$PROFILE_DIR/Default/Preferences"
if [ -f "$PREFS" ]; then
    sed -i 's/"exited_cleanly":false/"exited_cleanly":true/; s/"exit_type":"Crashed"/"exit_type":"Normal"/' "$PREFS"
fi

# Wait for the local setup server to be listening (it is ordered before us
# but systemd only knows the process started, not that the port is bound).
for _ in $(seq 1 30); do
    curl -fs -o /dev/null http://127.0.0.1:8080/status && break
    sleep 0.5
done

exec cage -d -- chromium \
    --kiosk \
    --user-data-dir="$PROFILE_DIR" \
    --ozone-platform=wayland \
    --no-first-run \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --autoplay-policy=no-user-gesture-required \
    --enable-features=AcceleratedVideoDecodeLinuxGL \
    --disable-component-update \
    --password-store=basic \
    http://127.0.0.1:8080/
