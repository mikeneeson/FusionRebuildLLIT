# LuckyLogic Player

Turns a bare x86 mini PC into a signage player for Pilates studios. The
player does one thing: it boots into a fullscreen browser pointed at the
studio's controller page (served by a Synology NAS on the studio network,
not part of this repo). No desktop, no chrome, no prompts, nothing else
on screen.

Target: Debian 13 (Trixie) minimal, 64-bit, on used corporate minis
(HP ProDesk 600 G4 Mini, Dell OptiPlex 7040 Micro, Dell Wyse 5070).

## Install

On a fresh Debian minimal install with networking up:

```
curl -sSL https://central.luckylogic.com.au/player/install.sh | sudo bash
```

Re-running the same command is how updates are applied. The configured
controller URL survives updates.

**One manual step per box:** in the BIOS, enable *Power On after AC Loss*
(Dell: *AC Recovery: Power On*; HP: *After Power Loss: Power On*). That is
what brings the player back from a power cut with nobody touching it.

## What the installer does

- Installs cage (Wayland kiosk compositor), Chromium, grim and Python 3
  from Debian repos. No desktop environment, no display manager.
- Creates an unprivileged `player` user. Its only privilege is one sudoers
  line allowing `systemctl restart luckylogic-kiosk.service`.
- Installs two always-on services:
  - `luckylogic-kiosk` runs cage + Chromium fullscreen on tty1 as `player`,
    with `Restart=always`. A Chromium crash or OOM kill is back on screen
    in a few seconds.
  - `luckylogic-setup` is a small stdlib-Python web server on port 8080.
    With no URL configured it serves the branded setup screen; with a URL
    configured it serves a splash that polls the controller and redirects
    once it answers, so boot order against the NAS never matters.
- Writes a Chromium managed policy (`/etc/chromium/policies/managed/`)
  that suppresses the first-run terms dialog, update checks, telemetry
  and sign-in, and force-allows autoplay without a user gesture.
- Disables and masks `getty@tty1` (it fights cage for the console).
- Arms the hardware watchdog (`RuntimeWatchdogSec=30s`): a full kernel
  hang resets the board and the player boots straight back.
- Installs a nightly kiosk restart at 04:30 for long-run hygiene.
- Records the installed version in `/var/lib/luckylogic/version`.

## First boot and changing the URL

With no URL configured the TV shows the setup screen, including the
player's own IP address. From a phone on the studio network open:

```
http://<player-ip>:8080/setup
```

Enter the controller address. The player tests it is actually reachable
before saving (tick the override box if the NAS happens to be down), then
the kiosk restarts into it. The same page changes the URL later at any
time. The URL is stored in plain text at `/var/lib/luckylogic/url`,
owned by the `player` user.

## Checking the screen remotely

```
ssh <admin>@<player-ip> sudo luckylogic-screenshot > screen.png
```

Captures the real composited output via grim, exactly what the TV shows.

## Updating a player

Either re-run the install command above, or:

```
sudo luckylogic-update
```

which fetches the current installer from central, compares its version
stamp against `/var/lib/luckylogic/version`, and installs only if newer.
Deciding *when* to update is deliberately manual in v1; wire
`luckylogic-update` to a systemd timer if that ever changes.

## Cutting a release

The repo is private and players never hold GitHub credentials, so
distribution is a static tarball on central:

```
./release.sh 1.0.0
```

produces `dist/luckylogic-player-1.0.0.tar.gz`, its `.sha256`, and an
`install.sh` stamped with the version and checksum. Upload all three to
`https://central.luckylogic.com.au/player/`. The stable install.sh URL
then serves the new release; the stamped checksum means a tampered or
truncated tarball refuses to install.

For development, `sudo ./install.sh` from a checkout installs the working
tree directly (VERSION=dev), skipping the download.

## Repo layout

```
install.sh                     installer/updater (dev mode from checkout)
release.sh                     packages dist/ for upload to central
player/
  bin/kiosk-launch.sh          cage + Chromium launch, crash-restore guard
  bin/luckylogic-screenshot    live screen to PNG
  bin/luckylogic-update        version check + reinstall from central
  setup/setup_server.py        setup screen, splash/redirect, /status JSON
  systemd/                     kiosk, setup, nightly restart units
  chromium/policies.json       managed policy (first-run, autoplay, updates)
  system/sudoers               the one player privilege
  system/watchdog.conf         hardware watchdog config
```

`/status` on port 8080 returns JSON (version, URL, IP) and is the hook
point if fleet reporting is ever added. There is deliberately nothing
else: no device IDs, no tokens, no central management.

## Troubleshooting

- Blank screen: `systemctl status luckylogic-kiosk`, then
  `journalctl -u luckylogic-kiosk -e`.
- Setup page unreachable: `systemctl status luckylogic-setup`.
- What is on screen: `sudo luckylogic-screenshot > screen.png`.
- Wrong URL saved and no phone handy: edit `/var/lib/luckylogic/url`,
  then `systemctl restart luckylogic-kiosk`.
