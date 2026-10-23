"""Shared radar maths, simulated traffic, and the Pi-Sky reader.

Pi-Sky is only read. Nothing in this project writes to it.
"""

import json
import math
import os
import random
import time

try:
    import threading
except ImportError:
    threading = None

try:
    import urllib.error
    import urllib.request
except ImportError:
    urllib = None


class _NoLock:
    def __enter__(self):
        return None

    def __exit__(self, *_exc):
        return False


class _NoEvent:
    def __init__(self):
        self._flag = False

    def set(self):
        self._flag = True

    def is_set(self):
        return self._flag

    def wait(self, timeout=None):
        if timeout:
            time.sleep(timeout)


def _make_lock():
    if threading is None:
        return _NoLock()
    return threading.Lock()


def _make_event():
    if threading is None:
        return _NoEvent()
    return threading.Event()


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _size(path):
    try:
        return os.stat(path)[6]
    except OSError:
        return 0


def _mono():
    fn = getattr(time, "monotonic", None)
    if fn is not None:
        return fn()
    return time.ticks_ms() / 1000.0


def _clock():
    fmt = getattr(time, "strftime", None)
    if fmt is not None:
        return fmt("%H:%M:%S")
    parts = time.localtime()
    return "%02d:%02d:%02d" % (parts[3], parts[4], parts[5])


def _replace(src, dst):
    replace = getattr(os, "replace", None)
    if replace is not None:
        replace(src, dst)
        return
    try:
        os.remove(dst)
    except OSError:
        pass
    os.rename(src, dst)

EARTH_KM = 6371.0
NM_TO_KM = 1.852

DEFAULT_CONFIG = {
    "http_host": "0.0.0.0",
    "http_port": 80,
    "mode": "simulate",
    "pisky_url": "http://127.0.0.1:5050",
    "receiver_lat": 52.52,
    "receiver_lon": 13.405,
    "range_km": 50,
    "sim_count": 8,
    "max_labels": 5,
    "theme": "phosphor",
}

RANGE_CHOICES = (10, 25, 50, 100, 150, 250)
THEMES = {
    "phosphor": {
        "bg": [0, 0, 0],
        "face": [0, 18, 8],
        "ring": [31, 143, 74],
        "ring_dim": [20, 92, 50],
        "cross": [20, 102, 58],
        "text": [216, 255, 226],
        "text_dim": [111, 191, 136],
        "ownship": [255, 213, 106],
        "sweep": [190, 255, 190],
        "blip": [157, 255, 176],
        "blip_hot": [244, 255, 246],
    },
    "amber": {
        "bg": [8, 4, 0],
        "face": [32, 14, 0],
        "ring": [214, 122, 24],
        "ring_dim": [140, 72, 12],
        "cross": [120, 62, 8],
        "text": [255, 220, 160],
        "text_dim": [196, 140, 70],
        "ownship": [255, 244, 214],
        "sweep": [255, 176, 64],
        "blip": [255, 196, 96],
        "blip_hot": [255, 236, 200],
    },
    "arctic": {
        "bg": [0, 4, 12],
        "face": [0, 18, 32],
        "ring": [42, 168, 190],
        "ring_dim": [22, 102, 122],
        "cross": [16, 82, 104],
        "text": [214, 246, 255],
        "text_dim": [112, 182, 198],
        "ownship": [255, 214, 120],
        "sweep": [150, 240, 255],
        "blip": [126, 226, 242],
        "blip_hot": [236, 255, 255],
    },
    "night": {
        "bg": [10, 0, 0],
        "face": [28, 2, 2],
        "ring": [186, 42, 38],
        "ring_dim": [112, 22, 20],
        "cross": [92, 16, 16],
        "text": [255, 196, 186],
        "text_dim": [190, 104, 94],
        "ownship": [255, 214, 150],
        "sweep": [255, 86, 74],
        "blip": [255, 124, 104],
        "blip_hot": [255, 228, 220],
    },
    "day": {
        "bg": [232, 228, 214],
        "face": [214, 222, 208],
        "ring": [36, 78, 48],
        "ring_dim": [92, 112, 92],
        "cross": [70, 92, 74],
        "text": [22, 34, 26],
        "text_dim": [62, 82, 66],
        "ownship": [156, 48, 22],
        "sweep": [18, 92, 48],
        "blip": [22, 72, 40],
        "blip_hot": [8, 36, 18],
    },
}
AIRLINES = (
    "DLH", "BAW", "AFR", "KLM", "SAS", "RYR", "EZY", "NAX",
    "UAL", "AAL", "QTR", "UAE", "SWR", "AUA", "LOT", "FIN",
    "BEL", "IBE", "TAP", "AZA",
)
AIRLINE_INFO = {
    "DLH": ("Lufthansa", "A20N"),
    "BAW": ("British Airways", "A320"),
    "AFR": ("Air France", "A359"),
    "KLM": ("KLM", "B789"),
    "SAS": ("SAS", "A20N"),
    "RYR": ("Ryanair", "B738"),
    "EZY": ("easyJet", "A320"),
    "NAX": ("Norwegian", "B38M"),
    "UAL": ("United", "B772"),
    "AAL": ("American", "B738"),
    "QTR": ("Qatar", "A359"),
    "UAE": ("Emirates", "A388"),
    "SWR": ("SWISS", "A321"),
    "AUA": ("Austrian", "A320"),
    "LOT": ("LOT", "E195"),
    "FIN": ("Finnair", "A333"),
    "BEL": ("Brussels", "A20N"),
    "IBE": ("Iberia", "A321"),
    "TAP": ("TAP", "A339"),
    "AZA": ("ITA", "A320"),
}
AIRPORTS = (
    ("BER", "Berlin"),
    ("FRA", "Frankfurt"),
    ("MUC", "Munich"),
    ("LHR", "London"),
    ("CDG", "Paris"),
    ("AMS", "Amsterdam"),
    ("MAD", "Madrid"),
    ("FCO", "Rome"),
    ("VIE", "Vienna"),
    ("ZRH", "Zurich"),
    ("CPH", "Copenhagen"),
    ("ARN", "Stockholm"),
)
DETAIL_KEYS = ("from", "to", "from_city", "to_city", "airline", "type", "reg")


def distance_km(lat1, lon1, lat2, lon2):
    p1, l1, p2, l2 = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = p2 - p1
    dlon = l2 - l1
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1, lon1, lat2, lon2):
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def destination(lat, lon, bearing, km):
    br = math.radians(bearing)
    d = km / EARTH_KM
    p1 = math.radians(lat)
    l1 = math.radians(lon)
    p2 = math.asin(
        math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(br)
    )
    l2 = l1 + math.atan2(
        math.sin(br) * math.sin(d) * math.cos(p1),
        math.cos(d) - math.sin(p1) * math.sin(p2),
    )
    lon_out = (math.degrees(l2) + 540.0) % 360.0 - 180.0
    return math.degrees(p2), lon_out


def move_aircraft(lat, lon, track_deg, gs_knots, dt_s):
    km = max(0.0, gs_knots) * NM_TO_KM * (dt_s / 3600.0)
    return destination(lat, lon, track_deg, km)


def format_alt(alt):
    if alt is None:
        return ""
    alt = float(alt)
    if alt <= 50:
        return "GND"
    if alt >= 18000:
        return "FL%d" % int(round(alt / 100.0))
    return "%dft" % int(round(alt))


def clean_pisky_base(url):
    url = (url or "").strip().rstrip("/")
    for suffix in (
        "/api/dump1090/aircraft.json",
        "/data/aircraft.json",
        "/livemap",
        "/config",
        "/events",
        "/history",
        "/index.html",
    ):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    return url.rstrip("/")


def _num(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _altitude_ft(aircraft):
    alt = aircraft.get("alt_baro")
    if alt == "ground":
        return 0
    numeric = _num(alt)
    if numeric is not None:
        return numeric
    geom = _num(aircraft.get("alt_geom"))
    if aircraft.get("alt_geom") == "ground":
        return 0
    return geom


def normalize_dump1090(payload, receiver_lat, receiver_lon, max_age_s=45):
    """Turn a dump1090 / Pi-Sky aircraft.json document into scope contacts."""
    aircraft = payload.get("aircraft") if isinstance(payload, dict) else None
    if not isinstance(aircraft, list):
        raise ValueError("aircraft feed has no aircraft list")

    contacts = []
    unpositioned = 0
    for ac in aircraft:
        if not isinstance(ac, dict):
            continue
        seen_pos = _num(ac.get("seen_pos"))
        seen = _num(ac.get("seen"))
        age = seen_pos if seen_pos is not None else seen
        if age is not None and age > max_age_s:
            continue
        lat = _num(ac.get("lat"))
        lon = _num(ac.get("lon"))
        if lat is None or lon is None:
            unpositioned += 1
            continue
        cs = (ac.get("flight") or "").strip().upper()
        hex_code = str(ac.get("hex") or "").strip().upper()
        if not cs:
            cs = hex_code or "----"
        contacts.append(
            {
                "cs": cs[:8],
                "hex": hex_code,
                "lat": lat,
                "lon": lon,
                "alt": _altitude_ft(ac),
                "trk": _num(ac.get("track") if ac.get("track") is not None else ac.get("true_heading")),
                "gs": _num(ac.get("gs")),
                "vr": _num(ac.get("baro_rate") if ac.get("baro_rate") is not None else ac.get("geom_rate")),
            }
        )
    return contacts, unpositioned


def project_contacts(contacts, receiver_lat, receiver_lon, range_km, max_labels, unpositioned=0):
    projected = []
    for ac in contacts:
        km = distance_km(receiver_lat, receiver_lon, ac["lat"], ac["lon"])
        brg = bearing_deg(receiver_lat, receiver_lon, ac["lat"], ac["lon"])
        item = {
            "cs": ac["cs"],
            "hex": ac["hex"],
            "brg": round(brg, 1),
            "km": round(km, 2),
            "alt": None if ac.get("alt") is None else int(round(ac["alt"])),
            "trk": None if ac.get("trk") is None else int(round(ac["trk"])) % 360,
            "gs": None if ac.get("gs") is None else int(round(ac["gs"])),
            "vr": None if ac.get("vr") is None else int(round(ac["vr"])),
        }
        for key in DETAIL_KEYS:
            value = ac.get(key)
            if value:
                item[key] = str(value)[:22]
        projected.append(item)
    projected.sort(key=lambda item: item["km"])
    in_range = [item for item in projected if item["km"] <= range_km]
    return {
        "tracked": len(projected),
        "in_range": len(in_range),
        "unpositioned": unpositioned,
        "labels": max_labels,
        "aircraft": in_range[:30],
    }


class ConfigStore:
    def __init__(self, path):
        self.path = path
        self._lock = _make_lock()
        self._config = dict(DEFAULT_CONFIG)
        if _exists(path) and _size(path) > 0:
            self._config.update(_read_json(path))
        else:
            self._write(self._config)
        self._config = _validate(self._config)

    def get(self):
        with self._lock:
            return dict(self._config)

    def update(self, patch):
        with self._lock:
            merged = dict(self._config)
            merged.update(patch)
            cleaned = _validate(merged)
            self._write(cleaned)
            self._config = cleaned
            return dict(cleaned)

    def _write(self, config):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(json.dumps(config))
            fh.write("\n")
        _replace(tmp, self.path)


def _read_json(path):
    with open(path) as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("config must be a JSON object")
    return data


def _validate(raw):
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(raw)
    mode = str(cfg.get("mode") or "simulate").strip().lower()
    if mode not in ("simulate", "pisky"):
        raise ValueError("mode must be simulate or pisky")
    lat = float(cfg["receiver_lat"])
    lon = float(cfg["receiver_lon"])
    if not -90 <= lat <= 90:
        raise ValueError("latitude must be between -90 and 90")
    if not -180 <= lon <= 180:
        raise ValueError("longitude must be between -180 and 180")
    range_km = int(cfg["range_km"])
    if range_km not in RANGE_CHOICES:
        raise ValueError("range must be one of %s" % ", ".join(str(n) for n in RANGE_CHOICES))
    sim_count = int(cfg["sim_count"])
    if not 1 <= sim_count <= 24:
        raise ValueError("simulated aircraft must be between 1 and 24")
    labels = int(cfg["max_labels"])
    if not 0 <= labels <= 12:
        raise ValueError("labels must be between 0 and 12")
    theme = str(cfg.get("theme") or "phosphor").strip().lower()
    if theme not in THEMES:
        raise ValueError("theme must be one of %s" % ", ".join(THEMES))
    port = int(cfg["http_port"])
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    url = clean_pisky_base(str(cfg.get("pisky_url") or ""))
    if mode == "pisky" and not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("Pi-Sky address must start with http:// or https://")
    if not url:
        url = DEFAULT_CONFIG["pisky_url"]
    return {
        "http_host": str(cfg.get("http_host") or "0.0.0.0"),
        "http_port": port,
        "mode": mode,
        "pisky_url": url,
        "receiver_lat": lat,
        "receiver_lon": lon,
        "range_km": range_km,
        "sim_count": sim_count,
        "max_labels": labels,
        "theme": theme,
    }


class _Rng:
    def random(self):
        return random.random()

    def uniform(self, low, high):
        return random.uniform(low, high)

    def randint(self, low, high):
        return random.randint(low, high)

    def randrange(self, *args):
        return random.randrange(*args)

    def choice(self, seq):
        return random.choice(seq)


def _make_rng(rng=None):
    if rng is not None:
        return rng
    maker = getattr(random, "Random", None)
    if maker is not None:
        return maker()
    return _Rng()


class Simulator:
    def __init__(self, rng=None):
        self.rng = _make_rng(rng)
        self.craft = []
        self._key = None

    def configure(self, lat, lon, range_km, count):
        key = (round(lat, 4), round(lon, 4), int(count))
        if key != self._key or len(self.craft) != int(count):
            self._key = key
            self.craft = [self._spawn(lat, lon, range_km, low=(i < 2 and count >= 6)) for i in range(int(count))]
        self._home = (lat, lon)
        self._range = range_km

    def advance(self, dt_s, lat, lon, range_km):
        dt_s = max(0.0, min(float(dt_s), 2.0))
        if not self.craft:
            return
        self._range = range_km
        for idx, craft in enumerate(self.craft):
            craft["lat"], craft["lon"] = move_aircraft(
                craft["lat"], craft["lon"], craft["trk"], craft["gs"], dt_s
            )
            craft["alt"] = craft["alt"] + craft["vr"] * (dt_s / 60.0)
            floor = 600 if craft["low"] else 4000
            ceiling = 4500 if craft["low"] else 42000
            if craft["alt"] < floor:
                craft["alt"] = floor
                craft["vr"] = abs(craft["vr"]) or 200
            elif craft["alt"] > ceiling:
                craft["alt"] = ceiling
                craft["vr"] = -abs(craft["vr"]) or -200
            km = distance_km(lat, lon, craft["lat"], craft["lon"])
            if km > range_km * 1.25:
                self.craft[idx] = self._spawn(lat, lon, range_km, low=craft["low"])

    def _spawn(self, lat, lon, range_km, low=False):
        bearing = self.rng.uniform(0, 360)
        dist = self.rng.uniform(range_km * 0.08, range_km * 0.92)
        pos_lat, pos_lon = destination(lat, lon, bearing, dist)
        toward = bearing_deg(pos_lat, pos_lon, lat, lon)
        if self.rng.random() < 0.75:
            track = (toward + self.rng.uniform(-50, 50)) % 360
        else:
            track = self.rng.uniform(0, 360)
        if low:
            alt = self.rng.uniform(800, 2800)
            gs = self.rng.uniform(70, 140)
            vr = self.rng.uniform(-400, 400)
        else:
            alt = self.rng.uniform(8000, 39000)
            gs = self.rng.uniform(280, 520)
            vr = self.rng.uniform(-800, 800)
        identified = self.rng.random() > 0.15
        hex_code = "%06X" % self.rng.randrange(0x1000000)
        if identified:
            cs = "%s%d" % (self.rng.choice(AIRLINES), self.rng.randint(100, 9999))
            cs = cs[:8]
        else:
            cs = hex_code
        craft = {
            "cs": cs,
            "hex": hex_code,
            "lat": pos_lat,
            "lon": pos_lon,
            "alt": alt,
            "trk": track,
            "gs": gs,
            "vr": vr,
            "low": low,
        }
        craft.update(simulated_detail(cs, hex_code))
        return craft

    def contacts(self):
        return [
            {
                "cs": c["cs"],
                "hex": c["hex"],
                "lat": c["lat"],
                "lon": c["lon"],
                "alt": c["alt"],
                "trk": c["trk"],
                "gs": c["gs"],
                "vr": c["vr"],
                "from": c.get("from", ""),
                "to": c.get("to", ""),
                "from_city": c.get("from_city", ""),
                "to_city": c.get("to_city", ""),
                "airline": c.get("airline", ""),
                "type": c.get("type", ""),
                "reg": c.get("reg", ""),
            }
            for c in self.craft
        ]


def simulated_detail(callsign, hex_code):
    """Stand-in route card until Pi-Sky can supply the real one."""
    prefix = ""
    for airline in AIRLINE_INFO:
        if callsign.startswith(airline):
            prefix = airline
            break
    if not prefix:
        return {}
    name, aircraft_type = AIRLINE_INFO[prefix]
    slot = int(hex_code, 16) if hex_code else 0
    origin = AIRPORTS[slot % len(AIRPORTS)]
    dest = AIRPORTS[(slot // len(AIRPORTS) + 3) % len(AIRPORTS)]
    if dest[0] == origin[0]:
        dest = AIRPORTS[(slot + 1) % len(AIRPORTS)]
    return {
        "from": origin[0],
        "to": dest[0],
        "from_city": origin[1],
        "to_city": dest[1],
        "airline": name,
        "type": aircraft_type,
        "reg": "D-%s" % hex_code[-4:],
    }


def details_from_pisky_flights(flights):
    """Keep the short card fields from a Pi-Sky flight_update."""
    found = {}
    if not isinstance(flights, list):
        return found
    for flight in flights:
        if not isinstance(flight, dict):
            continue
        icao = str(flight.get("icao") or "").strip().upper()
        if not icao:
            continue
        detail = {}
        origin = _short(flight.get("origin"), 4)
        dest = _short(flight.get("destination"), 4)
        if origin:
            detail["from"] = origin
        if dest:
            detail["to"] = dest
        city_from = _short(flight.get("origin_city"), 16)
        city_to = _short(flight.get("destination_city"), 16)
        if city_from:
            detail["from_city"] = city_from
        if city_to:
            detail["to_city"] = city_to
        airline = _short(flight.get("airline_name"), 18)
        if airline:
            detail["airline"] = airline
        aircraft_type = _short(flight.get("aircraft_type") or flight.get("aircraft_model"), 12)
        if aircraft_type:
            detail["type"] = aircraft_type
        reg = _short(flight.get("aircraft_registration"), 8)
        if reg:
            detail["reg"] = reg
        if detail:
            found[icao] = detail
    return found


def apply_details(contacts, by_hex):
    if not by_hex:
        return contacts
    for ac in contacts:
        extra = by_hex.get(str(ac.get("hex") or "").upper())
        if extra:
            ac.update(extra)
    return contacts


def parse_sse_snapshot(raw):
    """Read the first data event from a Pi-Sky /events body."""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", "replace")
    else:
        text = raw
    payload = None
    for line in text.splitlines():
        if line.startswith("data:"):
            body = line[5:].strip()
            if body:
                payload = json.loads(body)
                break
    if not isinstance(payload, dict):
        return {}
    return details_from_pisky_flights(payload.get("flights") or [])


def _short(value, limit):
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "none" or text == "Unidentified":
        return ""
    return text[:limit]


def fetch_pisky(base_url, timeout=4):
    """Read receiver position and live aircraft from an unmodified Pi-Sky."""
    base = clean_pisky_base(base_url)
    if not (base.startswith("http://") or base.startswith("https://")):
        raise ValueError("Pi-Sky address must start with http:// or https://")
    config = _get_json(base + "/api/config", timeout)
    if not isinstance(config, dict):
        raise ValueError("Pi-Sky config was not a JSON object")
    lat = _num(config.get("receiver_lat"))
    lon = _num(config.get("receiver_lon"))
    if lat is None or lon is None:
        raise ValueError("Pi-Sky config has no receiver position")
    feed = _get_json(base + "/api/dump1090/aircraft.json", timeout)
    contacts, unpositioned = normalize_dump1090(feed, lat, lon)
    try:
        apply_details(contacts, fetch_pisky_details(base, timeout))
    except Exception:
        pass
    return lat, lon, contacts, unpositioned


def fetch_pisky_details(base, timeout=4):
    """Read Pi-Sky's live flight card fields. Positions still come from dump1090."""
    now = _mono()
    cache = getattr(fetch_pisky_details, "_cache", None)
    if cache and cache[0] == base and now - cache[1] < 8:
        return cache[2]
    raw = _read_first_event(base + "/events", timeout)
    details = parse_sse_snapshot(raw)
    fetch_pisky_details._cache = (base, now, details)
    return details


def _read_first_event(url, timeout):
    req = urllib.request.Request(
        url,
        headers={"Accept": "text/event-stream", "User-Agent": "presto-radar"},
    )
    chunks = []
    size = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        while size < 400000:
            block = resp.read(4096)
            if not block:
                break
            chunks.append(block)
            size += len(block)
            if b"\n\n" in block or b"\r\n\r\n" in b"".join(chunks):
                break
    return b"".join(chunks)


def _get_json(url, timeout):
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "presto-radar"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:180]
        raise ValueError("Pi-Sky returned HTTP %s from %s (%s)" % (exc.code, url, detail)) from exc
    except urllib.error.URLError as exc:
        raise ValueError("Cannot reach Pi-Sky at %s (%s)" % (url, exc.reason)) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Pi-Sky did not return JSON from %s" % url) from exc


def build_frame(config, source, ok, error, center_lat, center_lon, center_origin, contacts, unpositioned, presto):
    view = project_contacts(
        contacts,
        center_lat,
        center_lon,
        config["range_km"],
        config["max_labels"],
        unpositioned=unpositioned,
    )
    return {
        "v": 1,
        "ok": bool(ok),
        "mode": config["mode"],
        "source": source,
        "error": error or "",
        "range_km": config["range_km"],
        "theme": config["theme"],
        "palette": THEMES[config["theme"]],
        "center": {
            "lat": round(center_lat, 5),
            "lon": round(center_lon, 5),
            "origin": center_origin,
        },
        "clock": _clock(),
        "labels": view["labels"],
        "tracked": view["tracked"],
        "in_range": view["in_range"],
        "unpositioned": view["unpositioned"],
        "aircraft": view["aircraft"],
        "presto": presto,
    }


class Engine:
    def __init__(self, store):
        self.store = store
        self.sim = Simulator()
        self._lock = _make_lock()
        self._stop = _make_event()
        self._thread = None
        self.manual_live = False
        self._presto_at = None
        self._presto_ip = ""
        self._live_cache = None
        self._live_error = ""
        cfg = store.get()
        self.frame = self._simulate(cfg, 0.0)

    def start(self):
        if threading is None:
            return
        self._thread = threading.Thread(target=self._loop, name="radar-engine", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def note_presto(self, ip):
        with self._lock:
            self._presto_at = time.time()
            self._presto_ip = ip or ""

    def get_frame(self):
        with self._lock:
            frame = dict(self.frame)
            frame["presto"] = self._presto_status()
            frame["aircraft"] = list(self.frame["aircraft"])
            return frame

    def _presto_status(self):
        if self._presto_at is None:
            return {"seen_s": None, "ip": ""}
        return {"seen_s": round(time.time() - self._presto_at, 1), "ip": self._presto_ip}

    def note_live(self, lat, lon, contacts, unpositioned, error=""):
        with self._lock:
            if lat is not None and lon is not None:
                self._live_cache = (lat, lon, contacts, unpositioned, time.time())
            self._live_error = error or ""

    def tick(self, dt=None):
        if dt is None:
            now = _mono()
            previous = getattr(self, "_tick_at", now)
            dt = now - previous
            self._tick_at = now
        try:
            cfg = self.store.get()
            if cfg["mode"] == "simulate":
                frame = self._simulate(cfg, dt)
            elif self.manual_live:
                frame = self._from_cache(cfg)
            else:
                frame = self._live(cfg)
        except Exception as exc:
            cfg = self.store.get()
            frame = build_frame(
                cfg,
                "error",
                False,
                str(exc),
                cfg["receiver_lat"],
                cfg["receiver_lon"],
                "config",
                [],
                0,
                {"seen_s": None, "ip": ""},
            )
        with self._lock:
            frame["presto"] = self._presto_status()
            self.frame = frame
        return frame

    def _from_cache(self, cfg):
        cached = self._live_cache
        if cached and time.time() - cached[4] < 20:
            lat, lon, contacts, unpositioned, _when = cached
            return build_frame(
                cfg, "pi-sky", not self._live_error, self._live_error, lat, lon, "pi-sky", contacts, unpositioned, {}
            )
        return build_frame(
            cfg,
            "pi-sky",
            False,
            self._live_error or "Waiting for Pi-Sky",
            cfg["receiver_lat"],
            cfg["receiver_lon"],
            "config",
            [],
            0,
            {},
        )

    def _loop(self):
        last = _mono()
        while not self._stop.is_set():
            now = _mono()
            dt = now - last
            last = now
            self.tick(dt)
            self._stop.wait(0.5)

    def _simulate(self, cfg, dt):
        self.sim.configure(
            cfg["receiver_lat"], cfg["receiver_lon"], cfg["range_km"], cfg["sim_count"]
        )
        self.sim.advance(dt, cfg["receiver_lat"], cfg["receiver_lon"], cfg["range_km"])
        return build_frame(
            cfg,
            "simulator",
            True,
            "",
            cfg["receiver_lat"],
            cfg["receiver_lon"],
            "config",
            self.sim.contacts(),
            0,
            {"seen_s": None, "ip": ""},
        )

    def _live(self, cfg):
        try:
            lat, lon, contacts, unpositioned = fetch_pisky(cfg["pisky_url"])
            self._live_cache = (lat, lon, contacts, unpositioned, time.time())
            self._live_error = ""
        except Exception as exc:
            self._live_error = str(exc)
            if self._live_cache and time.time() - self._live_cache[4] < 20:
                lat, lon, contacts, unpositioned, _when = self._live_cache
                return build_frame(
                    cfg, "pi-sky", False, self._live_error, lat, lon, "pi-sky", contacts, unpositioned, {}
                )
            return build_frame(
                cfg,
                "pi-sky",
                False,
                self._live_error,
                cfg["receiver_lat"],
                cfg["receiver_lon"],
                "config",
                [],
                0,
                {},
            )
        return build_frame(
            cfg, "pi-sky", True, "", lat, lon, "pi-sky", contacts, unpositioned, {}
        )
