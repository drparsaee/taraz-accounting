"""Untrusted, LAN-only UDP discovery hints for an already configured HTTPS host.

Discovery has NO access to credentials, tokens, pairing approval or LAN state.
The advertised certificate fingerprint is a display hint, NEVER an approved pin.
Always compare the real host fingerprint using an independent trusted channel
before calling the authenticated native_app LAN join flow.

Only start DiscoveryResponder after the HTTPS LanService has started. No sockets
or broadcasts are opened merely by importing this module.
"""

from __future__ import annotations

from collections import OrderedDict
import ipaddress
import json
import re
import secrets
import socket
import threading
import time
from typing import Any

from lan import certificate_fingerprint


DISCOVERY_PORT = 48371  # fixed server UDP listen / response source port
BEACON_PORT = 48372     # fixed client UDP listen / beacon destination port
MAX_PACKET = 512
MAX_CANDIDATES = 32
MAX_PACKETS_PER_SCAN = 256
MAX_TTL = 15
BEACON_INTERVAL = 5.0
MAX_SCAN_SECONDS = 5.0
_RFC1918 = tuple(ipaddress.IPv4Network(network) for network in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))
_HEX16 = re.compile(r"[a-f0-9]{16}\Z")
_HEX32 = re.compile(r"[a-f0-9]{32}\Z")
_HEX64 = re.compile(r"[a-fA-F0-9]{64}\Z")
_SOLICIT_KEYS = {"v", "kind", "nonce"}
_ADVERT_KEYS = {"v", "kind", "name", "port", "fingerprint", "ttl", "id", "transport"}


def _peer_ipv4(value: str, *, test_loopback: bool = False) -> str | None:
    """Accept *only* RFC1918 unicast source IPs, with test-only loopback."""
    try:
        ip = ipaddress.IPv4Address(value)
    except (ValueError, ipaddress.AddressValueError, TypeError):
        return None
    if ip.is_loopback:
        return str(ip) if test_loopback else None
    if any(ip in network for network in _RFC1918) and not (
        ip.is_multicast or ip.is_unspecified or ip.is_reserved
    ):
        return str(ip)
    return None


def _host_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Discovery host name must be text")
    name = value.strip()
    if not 1 <= len(name) <= 64 or any(
        not char.isprintable() or char in "<>\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
        for char in name
    ):
        raise ValueError("Invalid discovery host name")
    return name


def _service_port(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError("Invalid HTTPS host port")
    return value


def _udp_port(value: Any, *, test_loopback: bool, standard_port: int) -> int:
    port = _service_port(value)
    if port != standard_port and not test_loopback:
        raise ValueError("LAN discovery uses a fixed UDP port")
    return port


def _encode(message: dict) -> bytes:
    raw = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_PACKET:
        raise ValueError("Discovery datagram is too large")
    return raw


def _decode(raw: bytes) -> dict | None:
    if not raw or len(raw) > MAX_PACKET:
        return None
    def unique_keys(pairs: list[tuple[str, object]]) -> dict:
        result: dict = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON discovery field")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_keys)
    except (ValueError, UnicodeError):
        return None
    return value if type(value) is dict else None


def _solicitation(raw: bytes) -> str | None:
    data = _decode(raw)
    if data is None or set(data) != _SOLICIT_KEYS or data.get("v") != 1 or (
        type(data["v"]) is not int or data.get("kind") != "solicit"
    ):
        return None
    nonce = data.get("nonce")
    return nonce if isinstance(nonce, str) and _HEX32.fullmatch(nonce) else None


def _advertisement(raw: bytes, nonce: str) -> dict | None:
    data = _decode(raw)
    if data is None or data.get("v") != 1 or type(data["v"]) is not int:
        return None
    kind = data.get("kind")
    if kind == "offer":
        if set(data) != _ADVERT_KEYS | {"nonce"} or data["nonce"] != nonce:
            return None
    elif kind == "beacon":
        if set(data) != _ADVERT_KEYS:
            return None
    else:
        return None
    try:
        name = _host_name(data["name"])
        host_port = _service_port(data["port"])
    except ValueError:
        return None
    ttl = data.get("ttl")
    fingerprint = data.get("fingerprint")
    server_id = data.get("id")
    if (
        type(ttl) is not int or not 1 <= ttl <= MAX_TTL or
        data.get("transport") != "https" or
        not isinstance(fingerprint, str) or not _HEX64.fullmatch(fingerprint) or
        not isinstance(server_id, str) or not _HEX16.fullmatch(server_id)
    ):
        return None
    return {"name": name, "port": host_port, "fingerprint": fingerprint.lower(),
            "ttl": ttl, "id": server_id}


class _Bucket:
    """Small bounded token bucket; keeps a UDP flood from amplifying replies."""

    def __init__(self, capacity: float, refill: float) -> None:
        self.capacity, self.refill = capacity, refill
        self.tokens = capacity
        self.last = time.monotonic()

    def take(self, now: float) -> bool:
        self.tokens = min(self.capacity, self.tokens + max(0.0, now - self.last) * self.refill)
        self.last = now
        if self.tokens < 1.0:
            return False
        self.tokens -= 1.0
        return True


class DiscoveryResponder:
    """Start/stop an optional HTTPS-only UDP LAN discovery responder.

    Production uses UDP 48371 and broadcasts beacons to UDP 48372. Private
    test knobs are restricted to loopback IPs and are NEVER bridge inputs.
    No pairing, HTTP requests, or PIN verification happen here.
    """

    def __init__(self, host_name: str, host_port: int, certfile=None, *,
                 discovery_port: int = DISCOVERY_PORT,
                 _test_loopback: bool = False, _test_bind: str | None = None,
                 _test_targets: tuple[str, ...] | None = None,
                 _test_beacon_port: int | None = None):
        self.name = _host_name(host_name)
        self.host_port = _service_port(host_port)
        self.certfile = certfile
        self._test_loopback = _test_loopback is True
        self.discovery_port = _udp_port(discovery_port, test_loopback=self._test_loopback,
                                        standard_port=DISCOVERY_PORT)
        self.beacon_port = _udp_port(
            _test_beacon_port if _test_beacon_port is not None else BEACON_PORT,
            test_loopback=self._test_loopback, standard_port=BEACON_PORT,
        )
        if self._test_loopback:
            self.bind = _test_bind or "127.0.0.1"
            targets = _test_targets or ("127.0.0.1",)
            if not ipaddress.IPv4Address(self.bind).is_loopback or not targets or any(
                not ipaddress.IPv4Address(target).is_loopback for target in targets
            ):
                raise ValueError("Test discovery must stay entirely on loopback")
        else:
            if _test_bind is not None or _test_targets is not None or _test_beacon_port is not None:
                raise ValueError("Custom bind/targets are test-only")
            self.bind = "0.0.0.0"
            targets = ("255.255.255.255",)
        self.targets = tuple(targets)
        self._instance_id = secrets.token_hex(8)
        self._fingerprint = ""
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._lock = threading.RLock()
        self._peers: OrderedDict[str, _Bucket] = OrderedDict()
        self._global = _Bucket(32, 8)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> int:
        with self._lock:
            if self.running:
                return self.discovery_port
            if self.certfile is None:
                raise ValueError("Discovery requires a configured HTTPS certificate")
            # The advertised pin is untrusted. The actual TLS client must check
            # the certificate over its own connection after human confirmation.
            fingerprint = certificate_fingerprint(self.certfile)
            if not _HEX64.fullmatch(fingerprint):
                raise ValueError("Invalid HTTPS certificate fingerprint")
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.bind((self.bind, self.discovery_port))
                sock.settimeout(0.15)
            except BaseException:
                sock.close()
                raise
            self._fingerprint = fingerprint.lower()
            self._socket = sock
            self._stopping.clear()
            self._peers.clear()
            self._global = _Bucket(32, 8)
            self._thread = threading.Thread(target=self._serve, daemon=True,
                                            name="madar-lan-discovery")
            self._thread.start()
            return self.discovery_port

    def stop(self) -> None:
        with self._lock:
            self._stopping.set()
            sock, thread = self._socket, self._thread
            self._socket = None
            if sock is not None:
                sock.close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        with self._lock:
            if self._thread is thread:
                self._thread = None

    def _payload(self, kind: str, *, nonce: str | None = None) -> bytes:
        msg = {"v": 1, "kind": kind, "name": self.name, "port": self.host_port,
               "fingerprint": self._fingerprint, "ttl": MAX_TTL,
               "id": self._instance_id, "transport": "https"}
        if nonce is not None:
            msg["nonce"] = nonce
        return _encode(msg)

    def _allow_reply(self, ip: str, now: float) -> bool:
        if not self._global.take(now):
            return False
        bucket = self._peers.get(ip)
        if bucket is None:
            if len(self._peers) >= 128:
                self._peers.popitem(last=False)
            bucket = self._peers[ip] = _Bucket(3, 1.0)
        else:
            self._peers.move_to_end(ip)
        return bucket.take(now)

    def _serve(self) -> None:
        beacon_due = time.monotonic()
        while not self._stopping.is_set():
            sock = self._socket
            if sock is None:
                return
            now = time.monotonic()
            if now >= beacon_due:
                payload = self._payload("beacon")
                for target in self.targets:
                    try:
                        sock.sendto(payload, (target, self.beacon_port))
                    except OSError:
                        pass  # firewall/broadcast availability is not pairing
                beacon_due = now + BEACON_INTERVAL
            try:
                raw, (peer_ip, peer_port) = sock.recvfrom(MAX_PACKET + 1)
            except socket.timeout:
                continue
            except ConnectionResetError:
                # Windows raises WSAECONNRESET after an earlier UDP beacon
                # reached an unopened port. The listener must survive it.
                continue
            except OSError as exc:
                if getattr(exc, "winerror", None) in (10040, 10054):
                    # WSAEMSGSIZE: oversized UDP packet is discarded by WinSock.
                    # WSAECONNRESET: a previous UDP send had no receiver.
                    continue
                return
            actual_ip = _peer_ipv4(peer_ip, test_loopback=self._test_loopback)
            if not actual_ip or not 1 <= peer_port <= 65535:
                continue
            nonce = _solicitation(raw)
            if nonce is None or not self._allow_reply(actual_ip, time.monotonic()):
                continue
            try:
                sock.sendto(self._payload("offer", nonce=nonce), (actual_ip, peer_port))
            except OSError:
                continue

    def __enter__(self) -> "DiscoveryResponder":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()


class DiscoveryClient:
    """Bounded passive beacon + active solicit discovery; no authentication."""

    def __init__(self, *, port: int = DISCOVERY_PORT,
                 _test_loopback: bool = False,
                 _test_targets: tuple[str, ...] | None = None,
                 _test_beacon_port: int | None = None):
        self._test_loopback = _test_loopback is True
        self.port = _udp_port(port, test_loopback=self._test_loopback,
                              standard_port=DISCOVERY_PORT)
        self.beacon_port = _udp_port(
            _test_beacon_port if _test_beacon_port is not None else BEACON_PORT,
            test_loopback=self._test_loopback, standard_port=BEACON_PORT,
        )
        if self._test_loopback:
            targets = _test_targets or ("127.0.0.1",)
            if not targets or any(not ipaddress.IPv4Address(ip).is_loopback for ip in targets):
                raise ValueError("Test discovery may only target loopback")
            self.bind = "127.0.0.1"
        else:
            if _test_targets is not None or _test_beacon_port is not None:
                raise ValueError("Custom beacon targets/ports are test-only")
            targets = ("255.255.255.255",)
            self.bind = "0.0.0.0"
        self.targets = tuple(targets)
        self._entries: dict[tuple[str, int], tuple[dict, float]] = {}
        self._lock = threading.Lock()

    def snapshot(self) -> list[dict]:
        """Only unexpired records; callers still MUST authenticate elsewhere."""
        now = time.monotonic()
        self._entries = {key: entry for key, entry in self._entries.items()
                         if entry[1] > now}
        return [dict(entry[0]) for _, entry in sorted(
            self._entries.items(), key=lambda item: (item[0][0], item[0][1])
        )]

    def discover(self, timeout: float = 1.5) -> list[dict]:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or (
            not 0.05 <= timeout <= MAX_SCAN_SECONDS
        ):
            raise ValueError("Discovery timeout must be 0.05 to 5 seconds")
        with self._lock:
            self.snapshot()
            nonce = secrets.token_hex(16)
            packet = _encode({"v": 1, "kind": "solicit", "nonce": nonce})
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.bind((self.bind, self.beacon_port))
                for target in self.targets:
                    sock.sendto(packet, (target, self.port))
                deadline = time.monotonic() + timeout
                received = 0
                while received < MAX_PACKETS_PER_SCAN:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    sock.settimeout(min(remaining, 0.2))
                    try:
                        raw, (peer_ip, peer_port) = sock.recvfrom(MAX_PACKET + 1)
                    except socket.timeout:
                        continue
                    except ConnectionResetError:
                        # Windows UDP: an unanswered solicitation can generate
                        # ICMP port-unreachable, not a fatal discovery error.
                        continue
                    except OSError as exc:
                        if getattr(exc, "winerror", None) in (10040, 10054):
                            continue
                        raise
                    received += 1
                    actual_ip = _peer_ipv4(peer_ip, test_loopback=self._test_loopback)
                    if actual_ip is None or peer_port != self.port:
                        continue
                    data = _advertisement(raw, nonce)
                    if data is None:
                        continue
                    key = (actual_ip, data["port"])
                    if len(self._entries) >= MAX_CANDIDATES and key not in self._entries:
                        continue
                    ttl = data["ttl"]
                    self._entries[key] = ({
                        "name": data["name"],
                        "url": f"https://{actual_ip}:{data['port']}",
                        "fingerprint": data["fingerprint"],
                        "verified": False,
                        "requires_pairing": True,
                        "peer_ip": actual_ip,
                        "host_port": data["port"],
                        "transport": "https",
                        "host_id": data["id"],
                        "ttl": ttl,
                        "expires_at": time.time() + ttl,
                    }, time.monotonic() + ttl)
                return self.snapshot()
            finally:
                sock.close()


def discover_hosts(timeout: float = 1.5, *, port: int = DISCOVERY_PORT) -> list[dict]:
    """List HTTPS candidates. NEVER use their fingerprint as an approved PIN.

    The UI must separately compare the full fingerprint with the real host
    and obtain account credentials/host approval before authenticated pairing.
    HTTPS is mandatory; discovery never requests HTTP or silently downgrades.
    """
    return DiscoveryClient(port=port).discover(timeout)
