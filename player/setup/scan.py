#!/usr/bin/env python3
"""Find devices on the local subnet so the user can pick the NAS from a list.

Standard library only. Runs on the player itself, called by the setup server.
Also runnable on its own for debugging:

    python3 scan.py            # human readable table
    python3 scan.py --json     # machine readable
    python3 scan.py --port 80  # also probe port 80 as the "wanted" port

The approach is a TCP connect sweep rather than ping. Ping needs raw sockets or
254 forked processes; a thread pool of connects is faster and needs no
privileges. Anything that answers on any of the probed ports is a device.
"""

import argparse
import concurrent.futures
import ipaddress
import json
import re
import socket
import struct
import subprocess
import sys

# Ports worth asking about. 5000/5001 are Synology DSM, which is the strongest
# hint that a box is the NAS we are looking for. 8888 is the Web Station port
# the controller page is normally served on.
DSM_PORTS = (5000, 5001)
WEB_PORTS = (8888, 80, 443)

# Synology's registered MAC prefixes. A match here is as close to certain as we
# can get without logging in to the thing.
SYNOLOGY_OUIS = ("00:11:32", "90:09:d0")

CONNECT_TIMEOUT = 0.3
WORKERS = 128
# Refuse to sweep anything bigger than a /22 (1022 hosts). A /16 would be 65k
# connects and the user would sit in front of a blank TV.
MIN_PREFIX = 22


# ---------------------------------------------------------------- local subnet

def _ip_command_network():
    """Ask iproute2 for the address on the interface holding the default route."""
    route = subprocess.run(
        ["ip", "-4", "-o", "route", "show", "default"],
        capture_output=True, text=True, timeout=5,
    )
    match = re.search(r"\bdev\s+(\S+)", route.stdout)
    if not match:
        return None
    iface = match.group(1)

    addr = subprocess.run(
        ["ip", "-4", "-o", "addr", "show", "dev", iface],
        capture_output=True, text=True, timeout=5,
    )
    match = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+/\d+)", addr.stdout)
    if not match:
        return None
    return iface, ipaddress.ip_interface(match.group(1))


def _socket_network():
    """Fallback for a box with no iproute2: find our own IP and assume a /24.

    The UDP connect sends no packets, it just makes the kernel pick the source
    address it would use to reach the internet.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 53))
        own = sock.getsockname()[0]
    finally:
        sock.close()
    return "unknown", ipaddress.ip_interface(own + "/24")


def local_network():
    """Return (iface, ip_interface) for the network we should scan."""
    try:
        found = _ip_command_network()
        if found:
            return found
    except (OSError, subprocess.SubprocessError):
        pass
    return _socket_network()


def hosts_to_scan(iface_addr):
    """Addresses to probe: the whole subnet, minus ourselves.

    A subnet wider than MIN_PREFIX is clamped to the /24 around our own address
    so a misconfigured /16 does not turn into a five minute scan.
    """
    network = iface_addr.network
    if network.prefixlen < MIN_PREFIX:
        network = ipaddress.ip_network(f"{iface_addr.ip}/24", strict=False)
    own = iface_addr.ip
    return network, [h for h in network.hosts() if h != own]


# ---------------------------------------------------------------------- probes

def open_ports(host, ports):
    """Return the ports this host accepts a TCP connection on."""
    found = []
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_TIMEOUT)
        try:
            if sock.connect_ex((str(host), port)) == 0:
                found.append(port)
        except OSError:
            pass
        finally:
            sock.close()
    return found


def arp_table():
    """ip -> MAC for hosts we have talked to. The sweep populates this for us."""
    table = {}
    try:
        result = subprocess.run(
            ["ip", "-4", "neigh", "show"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return table
    for line in result.stdout.splitlines():
        match = re.match(r"(\d+\.\d+\.\d+\.\d+).*\blladdr\s+([0-9a-f:]{17})", line)
        if match:
            table[match.group(1)] = match.group(2).lower()
    return table


def reverse_dns(host):
    """Hostname from the local resolver, or None. Often empty on a studio LAN."""
    try:
        socket.setdefaulttimeout(1.0)
        return socket.gethostbyaddr(str(host))[0]
    except (OSError, socket.herror):
        return None
    finally:
        socket.setdefaulttimeout(None)


def netbios_name(host, timeout=0.8):
    """Ask the host for its NetBIOS name on UDP 137.

    Reverse DNS usually returns nothing on a small LAN, but a Synology with SMB
    enabled answers this, and the answer is the name the customer actually gave
    the NAS. Worth the twenty lines.
    """
    # A node status request for the wildcard name "*". NetBIOS names are 16
    # bytes, padded with nulls, and each byte is sent as two nibbles offset
    # by the letter 'A'.
    raw = b"*" + b"\x00" * 15
    encoded = bytes(c for b in raw for c in (0x41 + (b >> 4), 0x41 + (b & 0x0F)))
    query = (
        struct.pack(">HHHHHH", 0x4C4C, 0x0000, 1, 0, 0, 0)
        + bytes([len(encoded)]) + encoded + b"\x00"
        + struct.pack(">HH", 0x0021, 0x0001)   # NBSTAT, IN
    )

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(query, (str(host), 137))
        data, _ = sock.recvfrom(2048)
    except OSError:
        return None
    finally:
        sock.close()

    # Header (12) + the echoed question (34 for our wildcard) + type, class,
    # ttl and rdlength (10) puts the name count here.
    offset = 12 + 34 + 10
    if len(data) < offset + 1:
        return None
    count = data[offset]
    offset += 1
    for _ in range(count):
        entry = data[offset:offset + 18]
        if len(entry) < 18:
            return None
        name = entry[:15].decode("ascii", "replace").strip()
        suffix, flags = entry[15], struct.unpack(">H", entry[16:18])[0]
        # Suffix 0x00 with the group bit clear is the machine's own name.
        if suffix == 0x00 and not flags & 0x8000:
            return name or None
        offset += 18
    return None


# --------------------------------------------------------------------- ranking

def score_device(device):
    """Higher is more likely to be the NAS. Drives the order of the list."""
    score = 0
    if device["synology"]:
        score += 100
    if any(p in DSM_PORTS for p in device["ports"]):
        score += 50
    if device["wanted_port"] in device["ports"]:
        score += 40
    if any(p in (80, 443) for p in device["ports"]):
        score += 10
    return score


def describe(device):
    """One short line telling the user why this row is in the list."""
    if device["synology"]:
        return "Synology hardware"
    dsm = [p for p in device["ports"] if p in DSM_PORTS]
    if dsm:
        return f"Synology DSM on {dsm[0]}"
    if device["wanted_port"] in device["ports"]:
        return f"Web server on {device['wanted_port']}"
    return "Web server on " + ", ".join(str(p) for p in device["ports"])


# ------------------------------------------------------------------- the sweep

def discover(wanted_port=8888, on_device=None):
    """Sweep the local subnet and return the devices found, best guess first.

    on_device, if given, is called with each device as it is found and again
    once its name has been looked up, so the setup page can fill in the list
    while the scan is still running. Callers key on the "ip" field.
    """
    iface, iface_addr = local_network()
    network, targets = hosts_to_scan(iface_addr)

    ports = tuple(dict.fromkeys((wanted_port,) + DSM_PORTS + WEB_PORTS))
    devices = {}

    def note(device):
        device["score"] = score_device(device)
        device["reason"] = describe(device)
        devices[device["ip"]] = device
        if on_device:
            on_device(device)

    with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
        # Pass one: who is alive, and on what.
        sweep = {pool.submit(open_ports, host, ports): host for host in targets}
        live = []
        for future in concurrent.futures.as_completed(sweep):
            found = future.result()
            if not found:
                continue
            host = sweep[future]
            live.append(host)
            note({
                "ip": str(host),
                "ports": found,
                "name": None,
                "mac": None,
                "synology": False,
                "wanted_port": wanted_port,
            })

        # Pass two: name the ones that answered. The sweep has already filled
        # the ARP table for us, so the MAC lookup is free.
        arp = arp_table()

        def name_it(host):
            device = devices[str(host)]
            device["mac"] = arp.get(str(host))
            device["synology"] = bool(
                device["mac"] and device["mac"][:8] in SYNOLOGY_OUIS
            )
            device["name"] = reverse_dns(host) or netbios_name(host)
            return device

        for future in concurrent.futures.as_completed(
            [pool.submit(name_it, host) for host in live]
        ):
            note(future.result())

    ordered = sorted(
        devices.values(),
        key=lambda d: (-d["score"], int(ipaddress.ip_address(d["ip"]))),
    )
    return {
        "interface": iface,
        "network": str(network),
        "own_ip": str(iface_addr.ip),
        "devices": ordered,
    }


def main():
    parser = argparse.ArgumentParser(description="Find devices on the local subnet.")
    parser.add_argument("--port", type=int, default=8888,
                        help="the port the controller page is on (default 8888)")
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args()

    result = discover(args.port)
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
        return

    print(f"Scanning {result['network']} on {result['interface']} "
          f"(this machine is {result['own_ip']})")
    if not result["devices"]:
        print("No devices found.")
        return
    for device in result["devices"]:
        ports = ",".join(str(p) for p in device["ports"])
        print(f"{device['ip']:<16} {device['name'] or '-':<24} "
              f"{device['reason']:<24} ports {ports}")


if __name__ == "__main__":
    main()
