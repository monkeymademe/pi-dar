"""Radar scope for the Pimoroni Presto.

The board draws the scope, serves the page, and reads Pi-Sky. Pi-Sky is
not modified.
"""

import json
import math
import sys
import time

try:
    import network
except ImportError:
    network = None

try:
    import uselect
except ImportError:
    uselect = None

try:
    from presto import Presto
except ImportError:
    Presto = None

try:
    from picovector import PicoVector
except ImportError:
    PicoVector = None

try:
    from picovector import ANTIALIAS_NONE
except ImportError:
    ANTIALIAS_NONE = None



def _wifi_from_json():
    with open("wifi_config.json", "r") as handle:
        data = json.load(handle)
    ssid = data.get("WIFI_SSID") or data.get("ssid")
    password = data.get("WIFI_PASSWORD")
    if password is None:
        password = data.get("password")
    return data, ssid, password


def load_wifi():
    try:
        _data, ssid, password = _wifi_from_json()
        if ssid and password:
            return ssid, password
    except Exception:
        pass
    try:
        import wifi_config
        ssid = getattr(wifi_config, "WIFI_SSID", None)
        password = getattr(wifi_config, "WIFI_PASSWORD", None)
        if ssid and password:
            return ssid, password
    except ImportError:
        pass
    return None, None


def _sync_clock():
    try:
        import ntptime
    except ImportError:
        return
    try:
        ntptime.timeout = 3
        ntptime.settime()
        print("clock ok")
    except Exception as exc:
        print("clock", type(exc).__name__)


def parse_url(url):
    if url.startswith("https://"):
        return None
    if url.startswith("http://"):
        rest = url[7:]
    else:
        return None
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


def polar(cx, cy, radius, bearing):
    rad = math.radians(bearing)
    return int(cx + radius * math.sin(rad)), int(cy - radius * math.cos(rad))


def format_alt(alt):
    if alt is None:
        return ""
    if alt <= 50:
        return "GND"
    if alt >= 18000:
        return "FL%d" % int(round(alt / 100))
    return "%dft" % int(round(alt))


def format_km(km):
    if km < 10:
        return "%.1fkm" % km
    return "%dkm" % int(round(km))


def board_alt(alt):
    if alt is None:
        return "----"
    if alt <= 50:
        return "GND"
    if alt >= 18000:
        return "FL%d" % int(round(alt / 100.0))
    return "%d" % int(round(alt))


def board_km(km):
    km = km or 0
    if km < 10:
        return "%.1f" % km
    return "%d" % int(round(km))


def board_vs(vr):
    if vr is None:
        return "----"
    vr = int(vr)
    if abs(vr) < 150:
        return "LVL"
    if vr > 0:
        return "+%d" % vr
    return "%d" % vr



class Scope:
    def __init__(self):
        if Presto is None:
            raise RuntimeError("presto module missing")
        # 240x240 is scaled up on the panel and the sweep can move.
        # Full 480 spends most of each frame pushing pixels to the display.
        try:
            self.presto = Presto(ambient_light=True)
        except Exception as exc:
            print("display", exc)
            self.presto = Presto()
        self.display = self.presto.display
        self.w, self.h = self.display.get_bounds()
        self.cx = self.w // 2
        self.cy = self.h // 2
        self.radius = min(self.w, self.h) // 2 - (28 if self.w >= 400 else 14)
        self.hud = 18 if self.w >= 400 else 16
        self.tag = 16
        self._pens()
        self.vector = None
        if PicoVector is not None:
            try:
                self.vector = PicoVector(self.display)
                if ANTIALIAS_NONE is not None:
                    self.vector.set_antialiasing(ANTIALIAS_NONE)
                loaded = ""
                for name in ("OpenSans-SemiBold.af", "Roboto-Medium.af"):
                    try:
                        self.vector.set_font(name, 20)
                        loaded = name
                        break
                    except Exception as exc:
                        print("font", name, exc)
                if not loaded:
                    self.vector = None
                else:
                    print("font", loaded)
            except Exception as exc:
                print("font", exc)
                self.vector = None
        try:
            self.presto.set_backlight(1.0)
        except Exception:
            pass
        self.backlight = 1.0
        self.frame = None
        self.frame_at = time.ticks_ms()
        self.pin = ""
        self._held = None
        self._was_down = False
        self._last_tap = 0
        self.ip = ""
        self.serial_buf = []
        self.serial_poll = None
        if uselect is not None:
            try:
                self.serial_poll = uselect.poll()
                self.serial_poll.register(sys.stdin, uselect.POLLIN)
            except Exception:
                self.serial_poll = None
        print("display", self.w, self.h)

    def _pens(self):
        d = self.display
        self.black = d.create_pen(0, 0, 0)
        self.face = d.create_pen(0, 18, 8)
        self.ring = d.create_pen(31, 143, 74)
        self.ring_dim = d.create_pen(20, 92, 50)
        self.dim = d.create_pen(20, 102, 58)
        self.muted = d.create_pen(111, 191, 136)
        self.paper = d.create_pen(216, 255, 226)
        self.amber = d.create_pen(255, 213, 106)
        self.sweep_pens = [
            d.create_pen(8, 30, 16),
            d.create_pen(12, 48, 24),
            d.create_pen(20, 80, 40),
            d.create_pen(40, 130, 64),
            d.create_pen(90, 190, 110),
            d.create_pen(170, 255, 180),
            d.create_pen(230, 255, 235),
        ]
        self.blip = d.create_pen(157, 255, 176)
        self.blip_hot = d.create_pen(244, 255, 246)
        self._theme = ""

    def _pen(self, color):
        return self.display.create_pen(int(color[0]), int(color[1]), int(color[2]))

    def _mix(self, start, end, amount):
        return tuple(int(start[i] + (end[i] - start[i]) * amount) for i in range(3))

    def _rgb(self, colors, key, fallback):
        value = colors.get(key) if isinstance(colors, dict) else None
        if isinstance(value, list) and len(value) == 3:
            try:
                return (int(value[0]), int(value[1]), int(value[2]))
            except Exception:
                return fallback
        return fallback

    def _use_palette(self):
        theme = "phosphor"
        colors = None
        if self.frame:
            theme = self.frame.get("theme") or theme
            colors = self.frame.get("palette")
        if theme == self._theme or not isinstance(colors, dict):
            return
        try:
            face = self._rgb(colors, "face", (0, 18, 8))
            sweep = self._rgb(colors, "sweep", (190, 255, 190))
            self.black = self._pen(self._rgb(colors, "bg", (0, 0, 0)))
            self.face = self._pen(face)
            self.ring = self._pen(self._rgb(colors, "ring", (31, 143, 74)))
            self.ring_dim = self._pen(self._rgb(colors, "ring_dim", (20, 92, 50)))
            self.dim = self._pen(self._rgb(colors, "cross", (20, 102, 58)))
            self.muted = self._pen(self._rgb(colors, "text_dim", (111, 191, 136)))
            self.paper = self._pen(self._rgb(colors, "text", (216, 255, 226)))
            self.amber = self._pen(self._rgb(colors, "ownship", (255, 213, 106)))
            self.blip = self._pen(self._rgb(colors, "blip", (157, 255, 176)))
            self.blip_hot = self._pen(self._rgb(colors, "blip_hot", (244, 255, 246)))
            self.sweep_pens = [
                self._pen(self._mix(face, sweep, step / 6.0)) for step in range(7)
            ]
            self._theme = theme
            print("theme", theme)
        except Exception as exc:
            print("theme", exc)

    def text(self, message, x, y, size, pen, align="left"):
        self.display.set_pen(pen)
        if self.vector:
            self.vector.set_font_size(size)
            width = len(message) * size // 2
            try:
                _vx, _vy, width, _vh = self.vector.measure_text(message)
                width = int(width)
            except Exception:
                pass
            if align == "center":
                x -= width // 2
            elif align == "right":
                x -= width
            self.vector.text(message, int(x), int(y))
            return
        scale = 2 if size >= 18 else 1
        width = len(message) * 8 * scale
        if align == "center":
            x -= width // 2
        elif align == "right":
            x -= width
        self.display.text(message, int(x), int(y - 8 * scale), self.w, scale)

    def _fit(self, message, size, max_w):
        message = str(message or "")
        if not message or not self.vector:
            return message
        self.vector.set_font_size(size)
        while message:
            try:
                _vx, _vy, width, _vh = self.vector.measure_text(message)
            except Exception:
                return message
            if int(width) <= max_w:
                return message
            message = message[:-1]
        return ""

    def _panel(self, x, y, width, height):
        d = self.display
        d.set_pen(self.ring)
        d.rectangle(int(x), int(y), int(width), int(height))
        if width > 2 and height > 2:
            d.set_pen(self.black)
            d.rectangle(int(x) + 1, int(y) + 1, int(width) - 2, int(height) - 2)

    def _mark(self, cx, cy, radius):
        d = self.display
        d.set_pen(self.face)
        d.circle(cx, cy, radius)
        for frac in (1.0, 0.66, 0.33):
            ring_r = max(3, int(radius * frac))
            d.set_pen(self.ring if frac == 1.0 else self.ring_dim)
            d.circle(cx, cy, ring_r)
            d.set_pen(self.face)
            d.circle(cx, cy, ring_r - 2)
        d.set_pen(self.dim)
        d.line(cx, cy - radius + 3, cx, cy + radius - 3)
        d.line(cx - radius + 3, cy, cx + radius - 3, cy)
        for step in range(7):
            x, y = polar(cx, cy, radius - 2, step * 7)
            d.set_pen(self.sweep_pens[min(len(self.sweep_pens) - 1, step)])
            d.line(cx, cy, x, y)
        bx, by = polar(cx, cy, int(radius * 0.62), 48)
        d.set_pen(self.blip_hot)
        d.circle(bx, by, 3 if radius < 50 else 4)
        d.set_pen(self.amber)
        d.circle(cx, cy, 2)

    def draw_message(self, detail, bright=False):
        d = self.display
        d.set_pen(self.black)
        d.clear()
        big = self.w >= 400
        radius = 52 if big else 40
        cy = self.cy - (36 if big else 24)
        self._mark(self.cx, cy, radius)
        self.text("Pi-Dar", self.cx, cy + radius + (30 if big else 24), 28 if big else 22, self.paper, "center")
        size = (22 if big else 18) if bright else (16 if big else 14)
        pen = self.paper if bright else self.muted
        self.text(str(detail), self.cx, cy + radius + (62 if big else 48), size, pen, "center")
        self.presto.update()

    def _show_address(self):
        shown = time.ticks_ms()
        if self.ip:
            print("wifi", self.ip)
            self.draw_message(self.ip, bright=True)
            _sync_clock()
        else:
            self.draw_message("No Wi-Fi")
        while time.ticks_diff(time.ticks_ms(), shown) < 2500:
            time.sleep(0.1)

    def connect_wifi(self):
        if network is None:
            self._show_address()
            return False
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        if not wlan.isconnected():
            ssid, password = load_wifi()
            if not ssid or not password:
                print("wifi config missing")
                self._show_address()
                return False
            self.draw_message("Joining Wi-Fi")
            try:
                wlan.connect(ssid, password)
            except Exception as exc:
                print("wifi", type(exc).__name__)
                self._show_address()
                return False
            for _ in range(40):
                if wlan.isconnected():
                    break
                time.sleep(0.25)
        if wlan.isconnected():
            self.ip = wlan.ifconfig()[0]
        self._show_address()
        return bool(self.ip)

    def read_serial(self):
        if self.serial_poll is None:
            return
        try:
            while self.serial_poll.poll(0):
                char = sys.stdin.read(1)
                if not char:
                    return
                if char == "\n":
                    line = "".join(self.serial_buf)
                    self.serial_buf = []
                    self._take_line(line)
                elif char != "\r":
                    if len(self.serial_buf) < 12000:
                        self.serial_buf.append(char)
                    else:
                        self.serial_buf = []
        except Exception:
            self.serial_poll = None

    def _take_line(self, line):
        line = line.strip()
        if not line.startswith("{"):
            return
        try:
            frame = json.loads(line)
        except Exception:
            return
        if isinstance(frame, dict) and "aircraft" in frame:
            self.frame = frame
            self.frame_at = time.ticks_ms()

    def accept_http(self, frame):
        if isinstance(frame, dict):
            self.frame = frame
            self.frame_at = time.ticks_ms()

    def poll_touch(self):
        try:
            self.presto.touch_poll()
            x, y, down = self.presto.touch_a
        except Exception:
            return
        down = bool(down)
        if not (down and not self._was_down):
            self._was_down = down
            return
        self._was_down = down
        x, y = self._touch_xy(x, y)
        if self.pin:
            self.pin = ""
            self._held = None
            print("touch close")
            return
        self._pin(x, y)

    def _touch_xy(self, x, y):
        x = int(x)
        y = int(y)
        if x > self.w or y > self.h:
            x = int(x * self.w / 480)
            y = int(y * self.h / 480)
        return x, y

    def _pin(self, x, y):
        best = None
        best_d = 50 if self.w < 400 else 64
        for ac in self._aircraft():
            px, py = self._blip_xy(ac)
            dist = math.sqrt((px - x) ** 2 + (py - y) ** 2)
            if dist < best_d:
                best = ac
                best_d = dist
        if not best:
            print("touch", x, y, "miss")
            return
        self.pin = best.get("hex") or ""
        self._held = best
        print("touch", x, y, self.pin, best.get("cs"))

    def _aircraft(self):
        if not self.frame:
            return []
        items = self.frame.get("aircraft") or []
        return items if isinstance(items, list) else []

    def _range(self):
        if not self.frame:
            return 50
        try:
            return max(1, int(self.frame.get("range_km") or 50))
        except Exception:
            return 50

    def _blip_xy(self, ac):
        km = ac.get("km") or 0
        span = self._range()
        dist = min(float(km) / span, 1.0) * self.radius
        return polar(self.cx, self.cy, dist, ac.get("brg") or 0)

    def _error(self):
        if self.frame is None:
            return "WAITING"
        if not self.frame.get("ok") and self.frame.get("error"):
            return str(self.frame.get("error"))[:48]
        return ""

    def draw(self):
        self._use_palette()
        if self.pin:
            self._draw_card()
            return
        sweep = (time.ticks_ms() % 4000) * 360 / 4000
        d = self.display
        d.set_pen(self.black)
        d.clear()
        d.set_pen(self.face)
        d.circle(self.cx, self.cy, self.radius)
        for frac in (1.0, 0.75, 0.5, 0.25):
            ring_r = int(self.radius * frac)
            d.set_pen(self.ring if frac in (1.0, 0.5) else self.ring_dim)
            d.circle(self.cx, self.cy, ring_r)
            d.set_pen(self.face)
            if ring_r > 3:
                d.circle(self.cx, self.cy, ring_r - 2)
        d.set_pen(self.dim)
        d.line(self.cx, self.cy - self.radius, self.cx, self.cy + self.radius)
        d.line(self.cx - self.radius, self.cy, self.cx + self.radius, self.cy)
        for deg in range(0, 360, 30):
            inner = self.radius - (14 if deg % 90 == 0 else 8)
            x1, y1 = polar(self.cx, self.cy, inner, deg)
            x2, y2 = polar(self.cx, self.cy, self.radius, deg)
            d.set_pen(self.ring)
            d.line(x1, y1, x2, y2)
        for deg, letter in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            x, y = polar(self.cx, self.cy, self.radius - 22, deg)
            self.text(letter, x, y + 4, 16, self.paper, "center")

        half = int(self._range() / 2)
        hx, hy = polar(self.cx, self.cy, int(self.radius * 0.5) + 10, 78)
        self.text(str(half), hx, hy, 14, self.muted, "left")

        for step in range(10, -1, -1):
            ang = sweep - step * 4.0
            x, y = polar(self.cx, self.cy, self.radius, ang)
            pen = self.sweep_pens[min(len(self.sweep_pens) - 1, (10 - step) // 2)]
            d.set_pen(pen)
            d.line(self.cx, self.cy, x, y)

        aircraft = self._aircraft()
        label_n = 5
        if self.frame:
            try:
                label_n = int(self.frame.get("labels") or 0)
            except Exception:
                label_n = 5
        labeled = []
        for ac in aircraft[:label_n]:
            labeled.append(ac.get("hex"))
        if self.pin:
            labeled.append(self.pin)
        placed = []
        gap = 34 if self.w >= 400 else 24

        for ac in aircraft:
            x, y = self._blip_xy(ac)
            delta = (sweep - (ac.get("brg") or 0) + 360) % 360
            hot = delta < 28
            d.set_pen(self.blip_hot if hot else self.blip)
            d.circle(x, y, 4 if hot else 3)
            trk = ac.get("trk")
            if trk is not None:
                hx2, hy2 = polar(x, y, 10, trk)
                d.line(x, y, hx2, hy2)
            show = ac.get("hex") in labeled
            if show:
                for px, py in placed:
                    if (px - x) * (px - x) + (py - y) * (py - y) < gap * gap:
                        show = False
                        break
            if show:
                alt = format_alt(ac.get("alt"))
                call = ac.get("cs") or ""
                tag = call if self.w < 400 else (call + " " + alt).strip()
                dist = math.sqrt((x - self.cx) ** 2 + (y - self.cy) ** 2)
                outward = dist < self.radius * 0.72
                lx, ly = polar(self.cx, self.cy, dist + (12 if outward else -12), ac.get("brg") or 0)
                align = "left" if lx >= self.cx else "right"
                self.text(tag, lx, ly, self.tag, self.paper, align)
                placed.append((x, y))

        d.set_pen(self.amber)
        d.circle(self.cx, self.cy, 3)
        d.line(self.cx - 8, self.cy, self.cx + 8, self.cy)
        d.line(self.cx, self.cy - 8, self.cx, self.cy + 8)

        mode = "SIM"
        clock = ""
        in_range = 0
        if self.frame:
            mode = "LIVE" if self.frame.get("mode") == "pisky" else "SIM"
            clock = str(self.frame.get("clock") or "")
            in_range = self.frame.get("in_range") or 0
        self.text(mode, 4, 18, self.hud, self.paper, "left")
        self.text(clock, self.w - 4, 18, self.hud, self.paper, "right")
        self.text("%dKM" % self._range(), 4, self.h - 2, self.hud, self.paper, "left")
        self.text("%s" % in_range, self.w - 4, self.h - 2, self.hud, self.paper, "right")
        error = self._error()
        if error:
            self.text(error[:18], self.cx, self.h - 2, self.tag, self.amber, "center")

    def _selected(self):
        for ac in self._aircraft():
            if ac.get("hex") == self.pin:
                self._held = ac
                return ac
        return self._held

    def _draw_card(self):
        ac = self._selected()
        d = self.display
        w, h = self.w, self.h
        big = w >= 400
        d.set_pen(self.black)
        d.clear()
        head = 72 if big else 48
        d.rectangle(0, 0, w, head)
        d.set_pen(self.amber)
        d.line(0, head, w, head)
        d.line(0, head + 1, w, head + 1)
        if not ac:
            self.text("NOT ON SCOPE", self.cx, self.cy, self.hud, self.amber, "center")
            return
        call = self._fit(str(ac.get("cs") or "----"), 28 if big else 22, w - 16)
        self.text(call, 8, 28 if big else 24, 28 if big else 22, self.paper, "left")
        meta = "  ".join(bit for bit in (ac.get("airline"), ac.get("type"), ac.get("reg")) if bit)
        if not meta:
            meta = "NO TYPE"
        meta = self._fit(meta.upper(), 16 if big else 13, w - 12)
        self.text(meta, 8, 58 if big else 42, 16 if big else 13, self.muted, "left")

        gap = 10 if big else 6
        box_h = 108 if big else 66
        box_top = head + (10 if big else 6)
        box_w = (w - gap * 3) // 2
        self._port(gap, box_top, box_w, box_h, "FROM", ac.get("from") or "----", ac.get("from_city") or "")
        self._port(w - gap - box_w, box_top, box_w, box_h, "TO", ac.get("to") or "----", ac.get("to_city") or "")

        grid_top = box_top + box_h + (8 if big else 5)
        foot = 22 if big else 14
        cell_h = (h - grid_top - foot - 4) // 2
        cell_w = (w - gap * 4) // 3
        cells = (
            ("ALT", board_alt(ac.get("alt"))),
            ("GS", "----" if ac.get("gs") is None else "%d" % int(ac.get("gs"))),
            ("KM", board_km(ac.get("km"))),
            ("BRG", "%03d" % int(ac.get("brg") or 0)),
            ("HDG", "---" if ac.get("trk") is None else "%03d" % int(ac.get("trk"))),
            ("FPM", board_vs(ac.get("vr"))),
        )
        for index, (label, value) in enumerate(cells):
            col = index % 3
            row = index // 3
            x = gap + col * (cell_w + gap)
            y = grid_top + row * (cell_h + 4)
            self._cell(x, y, cell_w, cell_h, label, value)
        on_scope = any(item.get("hex") == self.pin for item in self._aircraft())
        if not on_scope:
            note = "LEFT SCOPE"
        elif self.frame and self.frame.get("mode") == "pisky":
            note = "PI-SKY"
        else:
            note = "SIMULATED"
        self.text(note, self.cx, h - 3, 16 if big else 12, self.amber if note != "PI-SKY" else self.muted, "center")

    def _port(self, x, y, width, height, kicker, code, city):
        big = self.w >= 400
        self._panel(x, y, width, height)
        self.text(kicker, x + 6, y + (22 if big else 14), 16 if big else 12, self.muted, "left")
        code_size = 36 if big else 24
        code = self._fit(str(code or "----"), code_size, width - 10)
        self.text(code, x + width // 2, y + (64 if big else 40), code_size, self.paper, "center")
        city = self._fit(str(city or ""), 16 if big else 13, width - 10)
        if city:
            self.text(city, x + width // 2, y + height - (10 if big else 6), 16 if big else 13, self.muted, "center")

    def _cell(self, x, y, width, height, label, value):
        big = height >= 70
        self._panel(x, y, width, height)
        self.text(label, x + width // 2, y + (20 if big else 13), 16 if big else 12, self.muted, "center")
        value_size = 26 if big else 16
        value = self._fit(str(value), value_size, width - 6)
        self.text(value, x + width // 2, y + height - (12 if big else 6), value_size, self.paper, "center")

    def run(self):
        self.draw_message("Starting")
        time.sleep(0.8)
        self.connect_wifi()
        try:
            import onboard
            import radar_core
        except Exception as exc:
            self.draw_message(str(exc)[:22])
            return
        store = radar_core.ConfigStore("config.json")
        engine = radar_core.Engine(store)
        engine.manual_live = True
        engine.tick(0)
        web = onboard.Web(engine, lambda: self.ip)
        pisky = onboard.PiskyLink(engine)
        if web.error:
            print("http", web.error)
        self._frames = 0
        self._fps_t = time.ticks_ms()
        print("RADAR_READY")
        while True:
            try:
                cfg = store.get()
                if cfg.get("mode") == "pisky":
                    pisky.poll(cfg.get("pisky_url") or "")
                else:
                    pisky.idle()
                engine.tick()
                web.poll()
                frame = engine.get_frame()
                frame["device"] = "presto"
                self.accept_http(frame)
            except Exception as exc:
                sys.print_exception(exc)
            self.read_serial()
            self.poll_touch()
            try:
                self.draw()
                self.presto.update()
            except Exception as exc:
                sys.print_exception(exc)
                self.draw_message(str(exc)[:22])
                time.sleep(1)
            self._frames += 1
            if self._frames == 30:
                elapsed = time.ticks_diff(time.ticks_ms(), self._fps_t)
                print("frame_ms", elapsed // 30)


def main():
    Scope().run()


if __name__ == "__main__":
    main()
