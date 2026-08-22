#!/usr/bin/env python3
"""The setup screen.

Serves the branded setup page on port 7777. Shown fullscreen on the TV when no
URL is saved, and reachable from a phone or laptop on the same network at any
time, which is how a player gets pointed somewhere new without a site visit.

Standard library only, no framework, no build step, nothing fetched from the
internet, because a studio has to be able to set a player up with the WAN down.
"""

import argparse
import http.server
import json
import os
import pathlib
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request

import scan

HERE = pathlib.Path(__file__).resolve().parent
STATIC = HERE / "static"
CONF = pathlib.Path(os.environ.get("LUCKYLOGIC_CONF", "/var/lib/luckylogic/player.conf"))
SETUP_FLAG = CONF.parent / "setup-requested"

DEFAULT_PORT = 8888
DEFAULT_PATH = "control"
FETCH_TIMEOUT = 8


# ---------------------------------------------------------------------- config

def read_config():
    """Parse the KEY="value" config. Missing file is the same as empty."""
    values = {}
    if CONF.is_file():
        for line in CONF.read_text().splitlines():
            match = re.match(r'^([A-Z_]+)="?([^"]*)"?\s*$', line)
            if match:
                values[match.group(1)] = match.group(2)
    return values


def save_url(url):
    """Write the URL into the config, leaving every other setting alone.

    Written to a temporary file and renamed, so a power cut mid-save cannot
    leave a half written config that the kiosk then fails to read.
    """
    values = read_config()
    values["URL"] = url
    values.setdefault("VNC", "off")

    lines = [
        "# LuckyLogic Player configuration.",
        "# Written by the setup screen. Normally not edited by hand.",
        "",
        f'URL="{values["URL"]}"',
        f'VNC="{values["VNC"]}"',
        "",
    ]
    temp = CONF.with_suffix(".tmp")
    temp.write_text("\n".join(lines))
    temp.replace(CONF)

    # A configured player must not land back on the setup screen next boot.
    SETUP_FLAG.unlink(missing_ok=True)


def own_ip():
    """The address to tell the user to open on their phone."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 53))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


# ------------------------------------------------------------ building the URL

def build_url(host, port, path):
    """Turn the three parts into one URL.

    Tolerant on purpose. Someone typing on a phone may paste a whole URL into
    the host box, or type the folder with or without slashes, and all of it
    should end up in the same place.
    """
    host = (host or "").strip()
    if not host:
        raise ValueError("No address was entered.")

    # A pasted URL wins over the separate port and path boxes.
    if "//" in host or "/" in host or host.count(":") == 1:
        candidate = host if "//" in host else "http://" + host
        parsed = urllib.parse.urlsplit(candidate)
        if parsed.hostname:
            host = parsed.hostname
            port = parsed.port or port
            if parsed.path.strip("/"):
                path = parsed.path

    try:
        port = int(str(port).strip() or DEFAULT_PORT)
    except ValueError:
        raise ValueError(f'"{port}" is not a port number.')
    if not 1 <= port <= 65535:
        raise ValueError(f"{port} is not a port number. It has to be 1 to 65535.")

    path = (path or "").strip().strip("/")
    tail = f"/{path}/" if path else "/"
    return f"http://{host}:{port}{tail}"


def check_url(url):
    """Actually fetch the page. Returns (ok, message, title).

    The player does this rather than the browser, because whoever is setting it
    up may be on a phone that cannot reach the NAS even though the player can.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "LuckyLogic-Player"})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
            body = response.read(8192).decode("utf-8", "replace")
        match = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
        title = match.group(1).strip()[:80] if match else ""
        return True, "", title

    except urllib.error.HTTPError as error:
        host = urllib.parse.urlsplit(url).netloc
        if error.code == 404:
            return False, (f"{host} answered, but there is no page at "
                           f"{urllib.parse.urlsplit(url).path}. Check the folder name."), ""
        if error.code in (401, 403):
            return False, f"{host} answered but refused access ({error.code}).", ""
        return False, f"{host} answered with an error ({error.code} {error.reason}).", ""

    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            return False, ("Nothing answered within eight seconds. Check the address, "
                           "and that the NAS is switched on."), ""
        if isinstance(reason, ConnectionRefusedError):
            parsed = urllib.parse.urlsplit(url)
            return False, (f"{parsed.hostname} is there, but nothing is listening on "
                           f"port {parsed.port}. Check the port number."), ""
        return False, f"Could not reach it: {reason}", ""

    except (OSError, ValueError) as error:
        return False, f"Could not reach it: {error}", ""


# ----------------------------------------------------------------- the scan job

class ScanJob:
    """One network scan at a time, with results readable while it runs."""

    def __init__(self):
        self.lock = threading.Lock()
        self.devices = {}
        self.info = {}
        self.running = False

    def start(self, wanted_port):
        with self.lock:
            if self.running:
                return
            self.running = True
            self.devices = {}
            self.info = {}
        threading.Thread(target=self._run, args=(wanted_port,), daemon=True).start()

    def _run(self, wanted_port):
        try:
            result = scan.discover(wanted_port, on_device=self._found)
            info = {k: result[k] for k in ("interface", "network", "own_ip")}
        except Exception as error:                      # noqa: BLE001
            info = {"error": str(error)}
        with self.lock:
            self.info = info
            self.running = False

    def _found(self, device):
        with self.lock:
            self.devices[device["ip"]] = device

    def snapshot(self):
        with self.lock:
            devices = sorted(self.devices.values(),
                             key=lambda d: (-d["score"], d["ip"]))
            return {"running": self.running, "devices": devices, **self.info}


SCAN = ScanJob()


# -------------------------------------------------------------------- the server

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "LuckyLogicSetup/1.0"

    def log_message(self, fmt, *args):
        # One tidy line per request in the journal instead of the default noise.
        print(f"setup: {self.address_string()} {fmt % args}", flush=True)

    # -- helpers

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, name, content_type):
        path = STATIC / name
        if not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            return {}

    # -- routes

    def do_GET(self):
        route = urllib.parse.urlsplit(self.path).path
        if route in ("/", "/index.html"):
            self.send_file("index.html", "text/html; charset=utf-8")
        elif route == "/app.js":
            self.send_file("app.js", "application/javascript; charset=utf-8")
        elif route == "/style.css":
            self.send_file("style.css", "text/css; charset=utf-8")
        elif route == "/api/state":
            config = read_config()
            self.send_json({
                "url": config.get("URL", ""),
                "vnc": config.get("VNC", "off"),
                "own_ip": own_ip(),
                "hostname": socket.gethostname(),
                "default_port": DEFAULT_PORT,
                "default_path": DEFAULT_PATH,
            })
        elif route == "/api/scan":
            self.send_json(SCAN.snapshot())
        else:
            self.send_error(404)

    def do_POST(self):
        route = urllib.parse.urlsplit(self.path).path
        if route == "/api/scan":
            body = self.read_json()
            try:
                wanted = int(body.get("port") or DEFAULT_PORT)
            except (TypeError, ValueError):
                wanted = DEFAULT_PORT
            SCAN.start(wanted)
            self.send_json(SCAN.snapshot())

        elif route == "/api/save":
            self.save(self.read_json())

        else:
            self.send_error(404)

    def save(self, body):
        """Build the URL, prove it works, and only then write it."""
        try:
            url = build_url(body.get("host"), body.get("port"), body.get("path"))
        except ValueError as error:
            self.send_json({"ok": False, "url": "", "error": str(error)})
            return

        ok, message, title = check_url(url)
        if not ok:
            # A URL that does not answer is never written to the config.
            self.send_json({"ok": False, "url": url, "error": message})
            return

        try:
            save_url(url)
        except OSError as error:
            self.send_json({"ok": False, "url": url,
                            "error": f"The page works, but the setting could not be "
                                     f"saved: {error}"})
            return

        print(f"setup: saved {url}", flush=True)
        self.send_json({"ok": True, "url": url, "title": title})


def main():
    parser = argparse.ArgumentParser(description="LuckyLogic Player setup screen.")
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--bind", default="0.0.0.0")
    args = parser.parse_args()

    # Start scanning immediately, so the list is already filling in by the time
    # anyone looks at the screen.
    SCAN.start(DEFAULT_PORT)

    server = http.server.ThreadingHTTPServer((args.bind, args.port), Handler)
    print(f"setup: listening on http://{own_ip()}:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
