#!/usr/bin/env python3
"""LuckyLogic Player setup and splash server.

Runs permanently as the unprivileged 'player' user on port 8080, all
interfaces. Stdlib only. Three jobs:

  /        No controller URL configured: the branded setup page.
           URL configured: a splash page that polls the controller and
           redirects the kiosk to it once it answers. This is what makes
           boot order irrelevant: after a power cut the NAS can take
           minutes longer than the player, and the splash just waits.
  /setup   The setup form, always available. Reaching this from a phone
           (http://<player-ip>:8080/setup) is how the URL is changed later.
  /status  JSON state. The hook point for any future fleet reporting.

The controller URL is stored in /var/lib/luckylogic/url, plain text,
owned by 'player'. Saving a new URL restarts the kiosk via the single
sudoers-permitted systemctl command.
"""

import html
import json
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = 8080
STATE_DIR = "/var/lib/luckylogic"
URL_FILE = os.path.join(STATE_DIR, "url")
VERSION_FILE = os.path.join(STATE_DIR, "version")


# ---------------------------------------------------------------- state

def read_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def controller_url():
    return read_file(URL_FILE)


def player_version():
    return read_file(VERSION_FILE) or "unknown"


def save_controller_url(url):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = URL_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(url + "\n")
    os.replace(tmp, URL_FILE)


def player_ip():
    """Best-effort primary LAN IP. The UDP connect sends no packets; it just
    asks the kernel which source address it would route from."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(1)
            s.connect(("1.1.1.1", 53))
            return s.getsockname()[0]
    except OSError:
        pass
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True,
                             text=True, timeout=5).stdout.split()
        if out:
            return out[0]
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def check_reachable(url):
    """One real HTTP request to the URL the studio typed in."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "LuckyLogic-Player-setup"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            return True, "Controller responded (HTTP %d)." % resp.status
    except urllib.error.HTTPError as e:
        return False, ("The server answered with HTTP %d. The address is a "
                       "real server but the path looks wrong." % e.code)
    except Exception as e:
        reason = getattr(e, "reason", e)
        return False, "Could not reach it: %s" % reason


def restart_kiosk_soon():
    """Bounce the kiosk after the HTTP response has gone out."""
    def go():
        time.sleep(1.5)
        subprocess.run(
            ["sudo", "/usr/bin/systemctl", "restart",
             "luckylogic-kiosk.service"],
            check=False)
    threading.Thread(target=go, daemon=True).start()


# ---------------------------------------------------------------- pages

STYLE = """
:root { color-scheme: dark; }
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  background: #0c1116; color: #e6edf3;
  min-height: 100vh; display: flex; flex-direction: column;
  align-items: center; justify-content: center; padding: 2rem;
}
.card {
  background: #151c26; border: 1px solid #24303f; border-radius: 16px;
  padding: 2.5rem 3rem; max-width: 46rem; width: 100%;
  box-shadow: 0 20px 60px rgba(0,0,0,.5);
}
.brand { font-size: 1.6rem; font-weight: 700; margin-bottom: 1.6rem; }
.brand .lucky { color: #34d399; }
.brand .tag { color: #8b98a9; font-weight: 400; font-size: 1.1rem; margin-left: .5rem; }
h1 { font-size: 1.5rem; margin-bottom: 1rem; }
p { color: #aab6c4; line-height: 1.55; margin-bottom: 1rem; }
code, .ip {
  font-family: ui-monospace, "Cascadia Mono", monospace;
  background: #0c1116; border: 1px solid #24303f; border-radius: 8px;
  padding: .2rem .55rem; color: #7ee2b8; font-size: 1.05em;
}
.bigip { display: block; text-align: center; font-size: 1.5rem;
  padding: .8rem; margin: 1.2rem 0; }
form { margin-top: 1.4rem; }
input[type=url] {
  width: 100%; padding: .85rem 1rem; font-size: 1.05rem;
  background: #0c1116; color: #e6edf3;
  border: 1px solid #33414f; border-radius: 10px;
}
input[type=url]:focus { outline: 2px solid #34d399; border-color: transparent; }
label.force { display: flex; gap: .5rem; align-items: center;
  color: #8b98a9; font-size: .92rem; margin: .9rem 0; }
button {
  margin-top: .4rem; width: 100%; padding: .9rem; font-size: 1.05rem;
  font-weight: 600; color: #08130d; background: #34d399;
  border: 0; border-radius: 10px; cursor: pointer;
}
button:hover { background: #4ade9f; }
.error {
  background: #2a1519; border: 1px solid #6e2a33; color: #f3a1ab;
  border-radius: 10px; padding: .9rem 1.1rem; margin-bottom: 1.2rem;
}
.ok { color: #34d399; }
.footer { margin-top: 1.8rem; color: #5e6a78; font-size: .85rem;
  display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.spinner {
  width: 3rem; height: 3rem; margin: 1.5rem auto;
  border: 4px solid #24303f; border-top-color: #34d399;
  border-radius: 50%; animation: spin 1s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.center { text-align: center; }
a { color: #34d399; }
"""


def page(body):
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>LuckyLogic Player</title>"
            "<style>%s</style></head><body>%s</body></html>" % (STYLE, body))


def brand():
    return ("<div class='brand'><span class='lucky'>&#127808; Lucky</span>"
            "Logic<span class='tag'>Player</span></div>")


def footer():
    return ("<div class='footer'><span>Player IP: <span class='ip'>%s</span>"
            "</span><span>Player version: %s</span></div>"
            % (html.escape(player_ip()), html.escape(player_version())))


def setup_page(error="", value=""):
    err = "<div class='error'>%s</div>" % html.escape(error) if error else ""
    ip = html.escape(player_ip())
    return page(
        "<div class='card'>" + brand() +
        "<h1>Set up this player</h1>"
        "<p>Enter the address of the studio controller. You can type it here "
        "with a keyboard, or open this page from a phone on the same "
        "network:</p>"
        "<code class='bigip'>http://%s:%d/setup</code>" % (ip, PORT) +
        err +
        "<form method='post' action='/save'>"
        "<input type='url' name='url' required autofocus "
        "placeholder='http://nas.local:8181/' value='%s'>" % html.escape(value, quote=True) +
        "<label class='force'><input type='checkbox' name='force' value='1'>"
        "Save even if the controller can't be reached right now</label>"
        "<button type='submit'>Save and start</button>"
        "</form>" + footer() + "</div>")


def splash_page(url):
    esc = html.escape(url)
    target_js = json.dumps(url)
    return page(
        "<div class='card center'>" + brand() +
        "<div class='spinner'></div>"
        "<h1>Connecting to the controller&hellip;</h1>"
        "<p><code>%s</code></p>" % esc +
        "<p>This clears automatically as soon as the controller responds. "
        "To change the address, open <code>http://%s:%d/setup</code> from a "
        "phone on the studio network.</p>" % (html.escape(player_ip()), PORT) +
        footer() + "</div>"
        "<script>"
        "const target = %s;" % target_js +
        "async function poll() {"
        "  try {"
        "    await fetch(target, {mode: 'no-cors', cache: 'no-store'});"
        "    window.location = target;"
        "  } catch (e) { setTimeout(poll, 3000); }"
        "}"
        "poll();"
        "</script>")


def saved_page(url):
    return page(
        "<div class='card center'>" + brand() +
        "<h1 class='ok'>Saved</h1>"
        "<p>The TV will switch to the controller in a few seconds.</p>"
        "<p><code>%s</code></p>" % html.escape(url) +
        "<p><a href='/setup'>Change it again</a></p>" +
        footer() + "</div>")


# ---------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    server_version = "LuckyLogicPlayer"

    def send_html(self, content, status=200):
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            url = controller_url()
            self.send_html(splash_page(url) if url else setup_page())
        elif path == "/setup":
            self.send_html(setup_page(value=controller_url()))
        elif path == "/status":
            self.send_json({
                "version": player_version(),
                "controller_url": controller_url(),
                "ip": player_ip(),
            })
        else:
            self.send_html(page("<div class='card'>" + brand() +
                                "<h1>Not found</h1></div>"), status=404)

    def do_POST(self):
        if urlparse(self.path).path != "/save":
            self.send_html(page("<div class='card'><h1>Not found</h1></div>"),
                           status=404)
            return

        length = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        url = form.get("url", [""])[0].strip()
        force = form.get("force", [""])[0] == "1"

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            self.send_html(setup_page(
                error="That doesn't look like a valid address. It needs to "
                      "start with http:// or https://", value=url))
            return

        if not force:
            ok, message = check_reachable(url)
            if not ok:
                self.send_html(setup_page(
                    error=message + " Fix the address and try again, or "
                          "tick the box below to save it anyway.",
                    value=url))
                return

        save_controller_url(url)
        restart_kiosk_soon()
        self.send_html(saved_page(url))

    def log_message(self, fmt, *args):
        # Journal via stderr, one line per request, no noise beyond that.
        print("%s %s" % (self.address_string(), fmt % args), flush=True)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("LuckyLogic setup server listening on :%d" % PORT, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
