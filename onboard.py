"""Web page and Pi-Sky reader for the Presto.

The board serves the page and builds the picture. Pi-Sky is only read.
"""

import json
import time

try:
    import socket
except ImportError:
    socket = None

import radar_core


FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/mark.svg": ("mark.svg", "image/svg+xml"),
}
_BUSY = (11, 114, 115, 119)


def parse_url(url):
    if not url or not url.startswith("http://"):
        return None
    rest = url[7:]
    slash = rest.find("/")
    if slash == -1:
        hostport = rest
        path = "/"
    else:
        hostport = rest[:slash]
        path = rest[slash:]
    if ":" in hostport:
        host, port_text = hostport.rsplit(":", 1)
        try:
            port = int(port_text)
        except ValueError:
            return None
    else:
        host = hostport
        port = 80
    if not host:
        return None
    return host, port, path


class Grab:
    """One non-blocking HTTP/1.0 GET."""

    def __init__(self, url, limit=180000, stop_blank=False):
        self.url = url
        self.limit = limit
        self.stop_blank = stop_blank
        self.done = False
        self.body = b""
        self.error = ""
        self._sock = None
        self._buf = b""
        self._state = "start"
        self._started = time.ticks_ms()
        parsed = parse_url(url)
        if not parsed or socket is None:
            self.error = "bad url"
            self.done = True
            return
        self._host, port, self._path = parsed
        try:
            self._addr = socket.getaddrinfo(self._host, port)[0][-1]
        except OSError as exc:
            self.error = "dns %s" % exc
            self.done = True

    def poll(self):
        if self.done:
            return
        if time.ticks_diff(time.ticks_ms(), self._started) > 8000:
            self._fail("timeout")
            return
        if self._state == "start":
            self._connect()
        elif self._state == "send":
            self._send()
        elif self._state == "read":
            self._read()

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _connect(self):
        try:
            self._sock = socket.socket()
            self._sock.setblocking(False)
            self._sock.connect(self._addr)
        except OSError as exc:
            if not (exc.args and exc.args[0] in _BUSY):
                self._fail("connect %s" % exc)
                return
        self._state = "send"

    def _send(self):
        req = "GET %s HTTP/1.0\r\nHost: %s\r\nConnection: close\r\n\r\n" % (self._path, self._host)
        try:
            self._sock.send(req.encode())
        except OSError as exc:
            if exc.args and exc.args[0] in _BUSY:
                return
            self._fail("send %s" % exc)
            return
        self._state = "read"

    def _read(self):
        try:
            chunk = self._sock.recv(2048)
        except OSError as exc:
            if exc.args and exc.args[0] in _BUSY:
                return
            self._fail("recv %s" % exc)
            return
        if chunk:
            self._buf += chunk
            if len(self._buf) > self.limit:
                self._fail("too big")
                return
        head, sep, body = self._buf.partition(b"\r\n\r\n")
        if not sep:
            if not chunk:
                self._fail("no reply")
            return
        if self.stop_blank and (b"\n\n" in body or b"\r\n\r\n" in body):
            self._ok(body)
            return
        length = _content_length(head)
        if length is not None and len(body) >= length:
            self._ok(body[:length])
            return
        if not chunk:
            self._ok(body)

    def _ok(self, body):
        self.body = body
        self.done = True
        self.close()

    def _fail(self, message):
        self.error = message
        self.done = True
        self.close()


def _content_length(head):
    for line in head.split(b"\r\n")[:24]:
        if line.lower().startswith(b"content-length:"):
            try:
                return int(line.split(b":", 1)[1].strip())
            except ValueError:
                return None
    return None


class PiskyLink:
    def __init__(self, engine):
        self.engine = engine
        self.base = ""
        self.phase = "config"
        self.lat = None
        self.lon = None
        self.contacts = []
        self.unpositioned = 0
        self.details = {}
        self.details_at = 0
        self.config_at = 0
        self.grab = None
        self.next_ms = time.ticks_ms()

    def idle(self):
        self._close()

    def poll(self, base_url):
        base = radar_core.clean_pisky_base(base_url)
        if base != self.base:
            self.base = base
            self.phase = "config"
            self.lat = None
            self.lon = None
            self._close()
        if self.grab is None:
            if time.ticks_diff(time.ticks_ms(), self.next_ms) < 0:
                return
            path = "/api/config"
            stop_blank = False
            if self.phase == "aircraft":
                path = "/api/dump1090/aircraft.json"
            elif self.phase == "events":
                path = "/events"
                stop_blank = True
            self.grab = Grab(base + path, stop_blank=stop_blank)
        self.grab.poll()
        if not self.grab.done:
            return
        body, err = self.grab.body, self.grab.error
        self.grab = None
        if err:
            self.engine.note_live(self.lat, self.lon, self.contacts, self.unpositioned, err[:80])
            self.phase = "config"
            self.next_ms = time.ticks_add(time.ticks_ms(), 1500)
            return
        try:
            self._take(body)
        except Exception as exc:
            self.engine.note_live(self.lat, self.lon, self.contacts, self.unpositioned, type(exc).__name__)
            self.phase = "config"
            self.next_ms = time.ticks_add(time.ticks_ms(), 1500)

    def _take(self, body):
        now = time.ticks_ms()
        if self.phase == "config":
            payload = json.loads(body.decode())
            lat = radar_core._num(payload.get("receiver_lat"))
            lon = radar_core._num(payload.get("receiver_lon"))
            if lat is None or lon is None:
                raise ValueError("no position")
            self.lat = lat
            self.lon = lon
            self.config_at = now
            self.phase = "events" if time.ticks_diff(now, self.details_at) > 8000 else "aircraft"
            self.next_ms = now
            return
        if self.phase == "events":
            self.details = radar_core.parse_sse_snapshot(body)
            self.details_at = now
            if self.contacts:
                radar_core.apply_details(self.contacts, self.details)
                self.engine.note_live(self.lat, self.lon, self.contacts, self.unpositioned, "")
            self.phase = "aircraft"
            self.next_ms = now
            return
        payload = json.loads(body.decode())
        contacts, unpositioned = radar_core.normalize_dump1090(payload, self.lat, self.lon)
        radar_core.apply_details(contacts, self.details)
        self.contacts = contacts
        self.unpositioned = unpositioned
        self.engine.note_live(self.lat, self.lon, contacts, unpositioned, "")
        if time.ticks_diff(now, self.config_at) > 30000:
            self.phase = "config"
        elif time.ticks_diff(now, self.details_at) > 8000:
            self.phase = "events"
        else:
            self.phase = "aircraft"
        self.next_ms = time.ticks_add(now, 900)

    def _close(self):
        if self.grab:
            self.grab.close()
            self.grab = None


class Web:
    def __init__(self, engine, ip_fn):
        self.engine = engine
        self.ip_fn = ip_fn
        self.server = None
        self.error = ""
        if socket is None:
            self.error = "no socket"
            return
        server = socket.socket()
        try:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except OSError:
            pass
        try:
            server.bind(("0.0.0.0", 80))
            server.listen(8)
            server.setblocking(False)
        except OSError as exc:
            self.error = "port 80 %s" % exc
            server.close()
            return
        self.server = server

    def poll(self):
        if self.server is None:
            return
        try:
            conn, _addr = self.server.accept()
        except OSError:
            return
        try:
            conn.settimeout(1)
            self._handle(conn)
        except Exception as exc:
            print("http", type(exc).__name__)
        try:
            conn.close()
        except Exception:
            pass

    def _handle(self, conn):
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 12000:
            chunk = conn.recv(512)
            if not chunk:
                break
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        text = head.decode()
        first = text.split("\r\n", 1)[0] if text else ""
        parts = first.split(" ")
        method = parts[0] if parts else ""
        target = parts[1] if len(parts) > 1 else "/"
        path = target.split("?", 1)[0]
        length = 0
        for line in text.split("\r\n"):
            if line.lower().startswith("content-length:"):
                try:
                    length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    length = 0
        length = max(0, min(length, 8000))
        while len(rest) < length:
            chunk = conn.recv(512)
            if not chunk:
                break
            rest += chunk
        body = rest[:length]
        if method == "GET" and path == "/api/radar":
            frame = self.engine.get_frame()
            frame["device"] = "presto"
            self._json(conn, frame)
            return
        if method == "GET" and path == "/api/config":
            self._json(conn, self._public_config())
            return
        if method == "POST" and path == "/api/config":
            self._post_config(conn, body)
            return
        if method == "GET" and path in FILES:
            name, content_type = FILES[path]
            self._file(conn, name, content_type)
            return
        self._send(conn, "404 Not Found", b"not found", "text/plain; charset=utf-8")

    def _public_config(self):
        payload = self.engine.store.get()
        payload["lan_ip"] = self.ip_fn() or ""
        payload["hostname"] = "presto"
        payload["http_port"] = 80
        return payload

    def _post_config(self, conn, body):
        try:
            patch = json.loads(body.decode() or "{}")
        except ValueError:
            self._json(conn, {"error": "config must be JSON"}, "400 Bad Request")
            return
        if not isinstance(patch, dict):
            self._json(conn, {"error": "config must be a JSON object"}, "400 Bad Request")
            return
        allowed = (
            "mode",
            "pisky_url",
            "receiver_lat",
            "receiver_lon",
            "range_km",
            "sim_count",
            "max_labels",
            "theme",
        )
        patch = {key: patch[key] for key in patch if key in allowed}
        try:
            saved = self.engine.store.update(patch)
        except (TypeError, ValueError) as exc:
            self._json(conn, {"error": str(exc)}, "400 Bad Request")
            return
        saved["lan_ip"] = self.ip_fn() or ""
        saved["hostname"] = "presto"
        saved["http_port"] = 80
        self._json(conn, saved)

    def _json(self, conn, payload, status="200 OK"):
        raw = json.dumps(payload).encode()
        self._send(conn, status, raw, "application/json; charset=utf-8")

    def _file(self, conn, name, content_type):
        try:
            with open(name, "rb") as handle:
                body = handle.read()
        except OSError:
            self._send(conn, "404 Not Found", b"not found", "text/plain; charset=utf-8")
            return
        self._send(conn, "200 OK", body, content_type)

    def _send(self, conn, status, body, content_type):
        head = "HTTP/1.0 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n" % (
            status,
            content_type,
            len(body),
        )
        data = head.encode() + body
        try:
            conn.settimeout(3)
        except OSError:
            pass
        sent = 0
        stalls = 0
        while sent < len(data):
            try:
                count = conn.send(data[sent:sent + 512])
            except OSError:
                stalls += 1
                if stalls > 8:
                    print("http short", sent, len(data))
                    return
                continue
            if not count:
                print("http short", sent, len(data))
                return
            stalls = 0
            sent += count
