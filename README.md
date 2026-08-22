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

## The setup screen

When a player has no URL saved it shows the setup screen on the TV. It is also
served all the time at `http://<player-ip>:7777`, so a player can be pointed
somewhere new from a phone without anyone visiting the studio.

It builds the URL in three steps rather than asking anyone to type a long
address on a TV remote:

1. **Machine.** The player scans its own subnet and lists what it finds, with
   the Synology sorted to the top and labelled. Arrow keys to move, Enter to
   choose. There is a box to type an address into as well, and a scan again
   button. On a normal studio network the whole step is one press of Enter.
2. **Port.** Prefilled with 8888, with 80, 5000 and 5001 one press away.
3. **Folder.** Prefilled with `control`.

It shows the assembled URL back as you go. Before saving, the player itself
loads the page to prove it works, and reports the page title so you can see it
is the right one. A URL that does not answer is never saved, and the message
says what is actually wrong: wrong port, wrong folder, or nothing there at all.

Note the player does the checking, not the browser, because whoever is setting
it up may be on a phone that cannot reach the NAS even though the player can.

Once saved, the TV moves to the page on its own. If you saved it from a phone,
the TV follows within a couple of seconds.

## Changing the URL later

From any machine on the same network, open `http://<player-ip>:7777` and set it
again. That works whether or not a URL is already saved.

To force the TV itself back to the setup screen:

    sudo touch /var/lib/luckylogic/setup-requested
    sudo systemctl restart luckylogic-kiosk

Two ways to do that with no keyboard are still to come: a key sequence on the
air remote, and powering the box off and on three times in a row for when it is
frozen and the remote does nothing.

## Watching a player

    systemctl status luckylogic-kiosk      is it running
    journalctl -u luckylogic-kiosk -f      what it is doing, live
    sudo luckylogic-shot                   save a PNG of what is on the TV

To watch the real screen live from another machine:

    sudo luckylogic-vnc on

Then point any VNC viewer at the player's address on port 5900. TigerVNC is the
safe choice; older viewers sometimes struggle with wayvnc. There is no password.

    luckylogic-vnc          which it is, and whether it is actually listening
    sudo luckylogic-vnc off stop it

Live view runs as its own service, separate from the kiosk, for two reasons.
Turning it on or off takes effect within about five seconds and never interrupts
what is on the TV. And it keeps running while the kiosk restarts underneath it,
which is the situation you most want to be watching.

Leave it off for studio units. It has no password and exposes the screen to
anyone on that network.

## Layout

    bootstrap.sh                   clones the repo and runs install.sh
    install.sh                     the whole install, idempotent
    player/bin/kiosk-launch        decides what to show, starts cage
    player/bin/kiosk-session       runs inside cage: VNC, Chromium, watchdog
    player/bin/luckylogic-shot     screenshot of the live display
    player/bin/luckylogic-vnc      turn live screen viewing on or off
    player/bin/vnc-launch          the live view service itself
    player/bin/luckylogic-update   pull latest code and reinstall
    player/setup/server.py         the setup screen, on port 7777
    player/setup/scan.py           finds the NAS on the local network
    player/setup/static/           the setup page itself
    player/chromium/policies.json  Chromium managed policy
    player/systemd/               kiosk, setup and live view services
    player/config/                default config

## Hardware

Used corporate mini PCs: HP ProDesk 600 G4 Mini, Dell OptiPlex 7040 Micro,
Dell Wyse 5070. Intel integrated graphics with VA-API hardware H.264 decode.
Input is a 2.4GHz air remote that presents as a plain USB keyboard, so
navigation is arrow keys and Enter only. No mouse, no touch.
