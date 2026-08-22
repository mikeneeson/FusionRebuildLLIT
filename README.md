# LuckyLogic Player

Turns a bare Debian 13 machine into a signage player for a Pilates studio.

The studio's Synology NAS serves a controller page over Web Station. That page
lists classes, plays videos, and falls back to a photo screensaver. This player
is the box plugged into the TV, and its whole job is to show that page
fullscreen and never show anything else.

## Install

On a fresh Debian 13 install with no desktop environment, one command:

    curl -fsSL https://raw.githubusercontent.com/mikeneeson/FusionRebuildLLIT/main/bootstrap.sh | sudo bash

That clones the repo to `/opt/luckylogic-src` and runs the installer. It takes a
few minutes, mostly downloading Chromium. When it finishes the TV is already
showing the player, no reboot needed.

If you would rather see what you are running first, do it the long way:

    sudo apt install -y git
    git clone https://github.com/mikeneeson/FusionRebuildLLIT.git
    cd FusionRebuildLLIT
    sudo ./install.sh

Either way, running it again is how updates are applied. It never overwrites a
URL that has already been saved, so re-running on a working studio box is safe.
Once a player is installed, later updates are just:

    sudo luckylogic-update

The repo is public, so nothing secret can ever go in it. A studio's NAS address
lives in the config on that player only, never here.

## What the install does

- Installs cage, Chromium, and Intel hardware video decode. cage is a Wayland
  compositor that runs one fullscreen program and nothing else, so there is no
  desktop, no window manager and no login screen to go wrong.
- Creates a locked `player` system account that owns the screen and nothing
  else on the machine.
- Puts the code in `/opt/luckylogic` and the config in
  `/var/lib/luckylogic/player.conf`.
- Installs a Chromium policy that kills the first-run terms dialog, update
  checks, password prompts and session restore.
- Turns off the tty1 login prompt, which otherwise fights the player for the
  console.
- Installs and starts `luckylogic-kiosk.service`, which starts at power on and
  restarts itself within three seconds if Chromium ever dies.

Nothing is configured by hand afterwards.

## After a power cut

The box comes back on its own. Nobody needs to touch it.

A TV box normally boots faster than a NAS, so the first attempt to load the
page often fails. The player watches for this: as soon as the page starts
answering, it reloads itself onto it, rather than sitting on a connection error
until someone visits the studio.

## Changing the URL later

Not built yet. This is the next piece of work. Until then, a configured player
can be sent back to the setup screen with:

    sudo touch /var/lib/luckylogic/setup-requested
    sudo systemctl restart luckylogic-kiosk

Two ways back into setup are planned, so nobody needs a keyboard at a studio:
a key sequence on the air remote, and powering the box off and on three times
in a row for when it is frozen and the remote does nothing.

## Watching a player

    systemctl status luckylogic-kiosk      is it running
    journalctl -u luckylogic-kiosk -f      what it is doing, live
    sudo luckylogic-shot                   save a PNG of what is on the TV

For a box on the bench, set `VNC="on"` in `/var/lib/luckylogic/player.conf` and
restart the service. The real screen is then viewable from any VNC client on
the network at port 5900. Leave this off for studio units, because it exposes
the screen to everyone on a network we do not control.

## Layout

    bootstrap.sh                   clones the repo and runs install.sh
    install.sh                     the whole install, idempotent
    player/bin/kiosk-launch        decides what to show, starts cage
    player/bin/kiosk-session       runs inside cage: VNC, Chromium, watchdog
    player/bin/luckylogic-shot     screenshot of the live display
    player/bin/luckylogic-update   pull latest code and reinstall
    player/setup/scan.py           finds the NAS on the local network
    player/chromium/policies.json  Chromium managed policy
    player/systemd/               the kiosk service
    player/config/                default config

## Hardware

Used corporate mini PCs: HP ProDesk 600 G4 Mini, Dell OptiPlex 7040 Micro,
Dell Wyse 5070. Intel integrated graphics with VA-API hardware H.264 decode.
Input is a 2.4GHz air remote that presents as a plain USB keyboard, so
navigation is arrow keys and Enter only. No mouse, no touch.
