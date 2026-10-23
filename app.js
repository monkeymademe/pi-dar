const canvas = document.querySelector("#scope");
const ctx = canvas.getContext("2d");
const mark = document.querySelector("#mark");
const markCtx = mark.getContext("2d", { alpha: true });
const caption = document.querySelector("#caption");
const rows = document.querySelector("#rows");
const form = document.querySelector("#config");
const saveNote = document.querySelector("#save-note");
const screenStatus = document.querySelector("#screen-status");
const linkStatus = document.querySelector("#link-status");

let frame = null;
let hoverHex = "";
let selectedHex = "";
const detail = document.querySelector("#detail");

function polar(cx, cy, radius, bearing) {
  const rad = bearing * Math.PI / 180;
  return [cx + radius * Math.sin(rad), cy - radius * Math.cos(rad)];
}

function formatAlt(alt) {
  if (alt === null || alt === undefined) return "";
  if (alt <= 50) return "GND";
  if (alt >= 18000) return "FL" + Math.round(alt / 100);
  return Math.round(alt) + "ft";
}

function formatKm(km) {
  return km < 10 ? km.toFixed(1) + " km" : Math.round(km) + " km";
}

const FALLBACK_PALETTE = {
  bg: [0, 0, 0],
  face: [0, 18, 8],
  ring: [31, 143, 74],
  ring_dim: [20, 92, 50],
  cross: [20, 102, 58],
  text: [216, 255, 226],
  text_dim: [111, 191, 136],
  ownship: [255, 213, 106],
  sweep: [190, 255, 190],
  blip: [157, 255, 176],
  blip_hot: [244, 255, 246],
};

function palette() {
  return frame && frame.palette ? frame.palette : FALLBACK_PALETTE;
}

function rgb(color, alpha) {
  if (alpha === undefined) return "rgb(" + color.join(",") + ")";
  return "rgba(" + color.join(",") + "," + alpha + ")";
}

function hex(color) {
  return "#" + color.map((part) => part.toString(16).padStart(2, "0")).join("");
}

function mix(a, b, t) {
  return a.map((part, index) => Math.round(part + (b[index] - part) * t));
}

function paintChrome(colors) {
  const light = colors.bg[0] + colors.bg[1] + colors.bg[2] > 380;
  const style = document.documentElement.style;
  style.colorScheme = light ? "light" : "dark";
  style.setProperty("--bg", hex(colors.bg));
  style.setProperty("--panel", hex(mix(colors.bg, colors.face, 0.72)));
  style.setProperty("--field", hex(light ? mix(colors.bg, [255, 255, 255], 0.45) : mix(colors.bg, [0, 0, 0], 0.45)));
  style.setProperty("--line", hex(colors.ring_dim));
  style.setProperty("--text", hex(colors.text));
  style.setProperty("--dim", hex(colors.text_dim));
  style.setProperty("--green", hex(colors.ring));
  style.setProperty("--amber", hex(colors.ownship));
  style.setProperty("--button", hex(mix(colors.face, colors.ring, light ? 0.18 : 0.35)));
  style.setProperty("--danger", light ? "#9c2b22" : "#ff9b8c");
}

function drawMark() {
  const colors = palette();
  const size = mark.width;
  const image = markCtx.createImageData(size, size);
  const data = image.data;
  function plot(x, y, color) {
    x = Math.round(x);
    y = Math.round(y);
    if (x < 0 || y < 0 || x >= size || y >= size) return;
    const index = (y * size + x) * 4;
    data[index] = color[0];
    data[index + 1] = color[1];
    data[index + 2] = color[2];
    data[index + 3] = 255;
  }
  function disc(cx, cy, radius, color) {
    const r = Math.round(radius);
    for (let y = -r; y <= r; y += 1) {
      for (let x = -r; x <= r; x += 1) {
        if (x * x + y * y <= r * r) plot(cx + x, cy + y, color);
      }
    }
  }
  function line(x0, y0, x1, y1, color) {
    x0 = Math.round(x0);
    y0 = Math.round(y0);
    x1 = Math.round(x1);
    y1 = Math.round(y1);
    const dx = Math.abs(x1 - x0);
    const dy = Math.abs(y1 - y0);
    const sx = x0 < x1 ? 1 : -1;
    const sy = y0 < y1 ? 1 : -1;
    let err = dx - dy;
    while (true) {
      plot(x0, y0, color);
      if (x0 === x1 && y0 === y1) break;
      const doubled = err * 2;
      if (doubled > -dy) {
        err -= dy;
        x0 += sx;
      }
      if (doubled < dx) {
        err += dx;
        y0 += sy;
      }
    }
  }
  const cx = 44;
  const cy = 44;
  const radius = 40;
  disc(cx, cy, radius, colors.face);
  for (const frac of [1, 0.66, 0.33]) {
    const ring = Math.max(3, Math.floor(radius * frac));
    disc(cx, cy, ring, frac === 1 ? colors.ring : colors.ring_dim);
    disc(cx, cy, ring - 2, colors.face);
  }
  line(cx, cy - radius + 3, cx, cy + radius - 3, colors.cross);
  line(cx - radius + 3, cy, cx + radius - 3, cy, colors.cross);
  for (let step = 0; step < 7; step += 1) {
    const [x, y] = polar(cx, cy, radius - 2, step * 7);
    line(cx, cy, x, y, mix(colors.face, colors.sweep, step / 6));
  }
  const [bx, by] = polar(cx, cy, Math.floor(radius * 0.62), 48);
  disc(bx, by, 3, colors.blip_hot);
  disc(cx, cy, 2, colors.ownship);
  markCtx.putImageData(image, 0, 0);
}

function draw() {
  drawMark();
  const w = canvas.width;
  const h = canvas.height;
  const cx = w / 2;
  const cy = h / 2;
  const radius = Math.min(w, h) / 2 - 36;
  const colors = palette();
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = rgb(colors.bg);
  ctx.fillRect(0, 0, w, h);
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.fillStyle = rgb(colors.face);
  ctx.fill();

  ctx.strokeStyle = rgb(colors.ring);
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.stroke();
  for (const frac of [0.75, 0.5, 0.25]) {
    ctx.beginPath();
    ctx.arc(cx, cy, radius * frac, 0, Math.PI * 2);
    ctx.strokeStyle = rgb(frac === 0.5 ? colors.ring : colors.ring_dim);
    ctx.stroke();
  }

  ctx.strokeStyle = rgb(colors.cross);
  ctx.beginPath();
  ctx.moveTo(cx, cy - radius);
  ctx.lineTo(cx, cy + radius);
  ctx.moveTo(cx - radius, cy);
  ctx.lineTo(cx + radius, cy);
  ctx.stroke();

  ctx.fillStyle = rgb(colors.text);
  ctx.font = "14px DejaVu Sans Mono, ui-monospace, monospace";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  for (let deg = 0; deg < 360; deg += 30) {
    const inner = deg % 90 === 0 ? radius - 14 : radius - 8;
    const [x1, y1] = polar(cx, cy, inner, deg);
    const [x2, y2] = polar(cx, cy, radius, deg);
    ctx.strokeStyle = rgb(colors.ring);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  }
  const letters = [[0, "N"], [90, "E"], [180, "S"], [270, "W"]];
  for (const [deg, letter] of letters) {
    const [x, y] = polar(cx, cy, radius - 24, deg);
    ctx.fillText(letter, x, y);
  }

  const range = frame ? frame.range_km : 50;
  ctx.fillStyle = rgb(colors.text_dim);
  ctx.font = "12px DejaVu Sans Mono, ui-monospace, monospace";
  ctx.textAlign = "left";
  const [lx, ly] = polar(cx, cy, radius * 0.5 + 8, 80);
  ctx.fillText(Math.round(range / 2) + "", lx, ly);

  const sweep = ((Date.now() / 1000) % 4) / 4 * 360;
  for (let i = 18; i >= 0; i -= 1) {
    const ang = sweep - i * 3.2;
    const [x, y] = polar(cx, cy, radius, ang);
    const alpha = i === 0 ? 0.95 : Math.max(0.04, 0.55 - i * 0.03);
    ctx.strokeStyle = rgb(colors.sweep, alpha);
    ctx.lineWidth = i === 0 ? 2 : 1;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(x, y);
    ctx.stroke();
  }

  const aircraft = frame && frame.aircraft ? frame.aircraft : [];
  const labelBudget = frame ? frame.labels : 5;
  const labeled = new Set(aircraft.slice(0, labelBudget).map((ac) => ac.hex));
  if (hoverHex) labeled.add(hoverHex);
  const placed = [];

  aircraft.forEach((ac) => {
    const dist = Math.min(ac.km / range, 1) * radius;
    const [x, y] = polar(cx, cy, dist, ac.brg);
    ac._x = x;
    ac._y = y;
    const delta = (sweep - ac.brg + 360) % 360;
    const hot = delta < 28;
    ctx.fillStyle = rgb(hot ? colors.blip_hot : colors.blip);
    ctx.beginPath();
    ctx.arc(x, y, hot ? 4 : 3, 0, Math.PI * 2);
    ctx.fill();
    if (ac.trk !== null && ac.trk !== undefined) {
      const [hx, hy] = polar(x, y, 14, ac.trk);
      ctx.strokeStyle = ctx.fillStyle;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(hx, hy);
      ctx.stroke();
    }
    if (ac.hex === selectedHex) {
      ctx.strokeStyle = rgb(colors.ownship);
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(x, y, 9, 0, Math.PI * 2);
      ctx.stroke();
    }
    const crowded = placed.some(([px, py]) => Math.hypot(px - x, py - y) < 36);
    if (labeled.has(ac.hex) && !crowded) {
      const alt = formatAlt(ac.alt);
      const text = alt ? ac.cs + " " + alt : ac.cs;
      const outward = dist < radius * 0.72;
      const [lx, ly] = polar(cx, cy, dist + (outward ? 18 : -16), ac.brg);
      ctx.font = "13px DejaVu Sans Mono, ui-monospace, monospace";
      ctx.textAlign = lx > cx ? "left" : "right";
      ctx.textBaseline = "middle";
      ctx.fillStyle = rgb(colors.text);
      ctx.fillText(text, lx, ly);
      placed.push([x, y]);
    }
  });

  ctx.strokeStyle = rgb(colors.ownship);
  ctx.fillStyle = rgb(colors.ownship);
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(cx, cy, 3, 0, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(cx - 8, cy);
  ctx.lineTo(cx + 8, cy);
  ctx.moveTo(cx, cy - 8);
  ctx.lineTo(cx, cy + 8);
  ctx.stroke();

  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  ctx.font = "14px DejaVu Sans Mono, ui-monospace, monospace";
  ctx.fillStyle = rgb(colors.text);
  const mode = frame ? (frame.mode === "pisky" ? "LIVE" : "SIM") : "SIM";
  ctx.fillText(mode, 12, 10);
  ctx.textAlign = "right";
  ctx.fillText(frame ? frame.clock || "" : "", w - 12, 10);
  ctx.textAlign = "left";
  ctx.textBaseline = "bottom";
  ctx.fillText(range + " KM", 12, h - 10);
  ctx.textAlign = "right";
  const count = frame ? frame.in_range + " IN RANGE" : "";
  ctx.fillText(count, w - 12, h - 10);

  if (frame && frame.error) {
    ctx.textAlign = "center";
    ctx.fillStyle = rgb(colors.ownship);
    ctx.fillText(frame.error.slice(0, 64), cx, h - 28);
  } else if (!frame) {
    ctx.textAlign = "center";
    ctx.fillStyle = rgb(colors.text);
    ctx.fillText("WAITING", cx, cy + 28);
  }

  const pinned = aircraft.find((ac) => ac.hex === (selectedHex || hoverHex));
  if (pinned) {
    const alt = formatAlt(pinned.alt);
    const gs = pinned.gs === null || pinned.gs === undefined ? "" : pinned.gs + " kt";
    const bits = [pinned.cs, formatKm(pinned.km), Math.round(pinned.brg) + "°", alt, gs].filter(Boolean);
    caption.textContent = bits.join("   ");
  } else if (frame && frame.aircraft && frame.aircraft.length) {
    caption.textContent = "Tap a blip, or a row, for the flight card.";
  } else if (frame) {
    caption.textContent = frame.ok ? "Scope is clear" : (frame.error || "No contacts");
  }
  requestAnimationFrame(draw);
}

function renderTable() {
  const aircraft = frame && frame.aircraft ? frame.aircraft : [];
  rows.replaceChildren();
  if (!aircraft.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.textContent = frame && frame.ok ? "Nothing inside this range" : "No contacts";
    tr.appendChild(td);
    rows.appendChild(tr);
    return;
  }
  for (const ac of aircraft) {
    const tr = document.createElement("tr");
    const cells = [
      ac.cs,
      formatKm(ac.km),
      Math.round(ac.brg) + "°",
      formatAlt(ac.alt) || "—",
      ac.trk === null || ac.trk === undefined ? "—" : ac.trk + "°",
      ac.gs === null || ac.gs === undefined ? "—" : ac.gs + " kt",
    ];
    for (const value of cells) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    }
    if (ac.hex === selectedHex) tr.className = "picked";
    tr.addEventListener("click", () => {
      selectedHex = ac.hex;
      renderDetail();
    });
    rows.appendChild(tr);
  }
}

function renderDetail() {
  const aircraft = frame && frame.aircraft ? frame.aircraft : [];
  const ac = aircraft.find((item) => item.hex === selectedHex);
  if (!ac) {
    selectedHex = "";
    detail.hidden = true;
    return;
  }
  detail.hidden = false;
  document.querySelector("#detail-call").textContent = ac.cs;
  const meta = [ac.airline, ac.type, ac.reg].filter(Boolean);
  document.querySelector("#detail-meta").textContent = meta.join("   ") || "No type yet";
  fillPort("#detail-from", "FROM", ac.from || "----", ac.from_city || "");
  fillPort("#detail-to", "TO", ac.to || "----", ac.to_city || "");
  const facts = document.querySelector("#detail-facts");
  facts.replaceChildren();
  const rowsToShow = [
    ["ALT", boardAlt(ac.alt)],
    ["GS", ac.gs === null || ac.gs === undefined ? "----" : String(ac.gs)],
    ["KM", boardKm(ac.km)],
    ["BRG", String(Math.round(ac.brg)).padStart(3, "0")],
    ["HDG", ac.trk === null || ac.trk === undefined ? "---" : String(ac.trk).padStart(3, "0")],
    ["FPM", boardVs(ac.vr)],
  ];
  for (const [name, value] of rowsToShow) {
    const cell = document.createElement("div");
    cell.className = "board-cell";
    const k = document.createElement("span");
    k.className = "k";
    k.textContent = name;
    const v = document.createElement("span");
    v.className = "v";
    v.textContent = value;
    cell.append(k, v);
    facts.append(cell);
  }
  const note = document.querySelector("#detail-note");
  note.textContent = frame && frame.mode === "pisky"
    ? "Pi-Sky"
    : "Simulated";
}

function fillPort(selector, kicker, code, city) {
  const node = document.querySelector(selector);
  node.replaceChildren();
  const k = document.createElement("span");
  k.className = "k";
  k.textContent = kicker;
  const c = document.createElement("span");
  c.className = "c";
  c.textContent = code;
  const n = document.createElement("span");
  n.className = "n";
  n.textContent = city;
  node.append(k, c, n);
}

function boardAlt(alt) {
  if (alt === null || alt === undefined) return "----";
  if (alt <= 50) return "GND";
  if (alt >= 18000) return "FL" + Math.round(alt / 100);
  return String(Math.round(alt));
}

function boardKm(km) {
  if (km < 10) return km.toFixed(1);
  return String(Math.round(km));
}

function boardVs(vr) {
  if (vr === null || vr === undefined) return "----";
  if (Math.abs(vr) < 150) return "LVL";
  return (vr > 0 ? "+" : "") + Math.round(vr);
}

function renderStatus(config) {
  if (!frame) return;
  const presto = frame.presto || {};
  if (frame.device === "presto") {
    screenStatus.textContent = "This Presto is drawing the scope.";
  } else if (presto.seen_s === null || presto.seen_s === undefined) {
    screenStatus.textContent = "The Presto has not asked for a picture yet.";
  } else {
    screenStatus.textContent = "Presto last asked " + presto.seen_s + "s ago" + (presto.ip ? " from " + presto.ip : "") + ".";
  }
  const origin = frame.center && frame.center.origin === "pi-sky" ? "from Pi-Sky" : "from this page";
  const centre = frame.center ? frame.center.lat.toFixed(4) + ", " + frame.center.lon.toFixed(4) : "";
  const extra = frame.unpositioned ? " " + frame.unpositioned + " heard with no position." : "";
  linkStatus.textContent = (frame.ok ? "Link is up. " : "Link is down. ") + frame.tracked + " positioned, " + frame.in_range + " inside " + frame.range_km + " km. Centre " + centre + " " + origin + "." + extra + (frame.error ? " " + frame.error : "");
  if (config && config.lan_ip) {
    const port = Number(config.http_port) === 80 ? "" : ":" + config.http_port;
    linkStatus.textContent += " Page http://" + config.lan_ip + port + "/";
  }
}

async function refresh() {
  try {
    const response = await fetch("/api/radar", { cache: "no-store" });
    frame = await response.json();
    if (frame.palette) paintChrome(frame.palette);
    renderTable();
    renderDetail();
    const config = await (await fetch("/api/config", { cache: "no-store" })).json();
    renderStatus(config);
  } catch (err) {
    caption.textContent = "The radar service is not answering.";
  }
}

function fillForm(config) {
  form.elements.mode.value = config.mode;
  form.elements.pisky_url.value = config.pisky_url || "";
  form.elements.receiver_lat.value = config.receiver_lat;
  form.elements.receiver_lon.value = config.receiver_lon;
  form.elements.range_km.value = String(config.range_km);
  form.elements.sim_count.value = config.sim_count;
  form.elements.max_labels.value = config.max_labels;
  if (config.theme && form.elements.theme) form.elements.theme.value = config.theme;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  saveNote.className = "";
  saveNote.textContent = "Saving…";
  const body = {
    mode: form.elements.mode.value,
    pisky_url: form.elements.pisky_url.value.trim(),
    receiver_lat: Number(form.elements.receiver_lat.value),
    receiver_lon: Number(form.elements.receiver_lon.value),
    range_km: Number(form.elements.range_km.value),
    sim_count: Number(form.elements.sim_count.value),
    max_labels: Number(form.elements.max_labels.value),
    theme: form.elements.theme.value,
  };
  const response = await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) {
    saveNote.className = "bad";
    saveNote.textContent = payload.error || "Could not save";
    return;
  }
  fillForm(payload);
  saveNote.textContent = "Saved. The scope will follow.";
});

canvas.addEventListener("click", (event) => {
  if (!frame || !frame.aircraft) return;
  const point = canvasPoint(event);
  let best = "";
  let bestDist = 32;
  for (const ac of frame.aircraft) {
    if (ac._x === undefined) continue;
    const dist = Math.hypot(ac._x - point.x, ac._y - point.y);
    if (dist < bestDist) {
      best = ac.hex;
      bestDist = dist;
    }
  }
  if (!best) return;
  selectedHex = best;
  renderDetail();
});

function canvasPoint(event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: (event.clientX - rect.left) * (canvas.width / rect.width),
    y: (event.clientY - rect.top) * (canvas.height / rect.height),
  };
}

canvas.addEventListener("mousemove", (event) => {
  if (!frame || !frame.aircraft) return;
  const point = canvasPoint(event);
  let best = "";
  let bestDist = 18;
  for (const ac of frame.aircraft) {
    if (ac._x === undefined) continue;
    const d = Math.hypot(ac._x - point.x, ac._y - point.y);
    if (d < bestDist) {
      best = ac.hex;
      bestDist = d;
    }
  }
  hoverHex = best;
});

canvas.addEventListener("mouseleave", () => {
  hoverHex = "";
});

fetch("/api/config", { cache: "no-store" }).then((r) => r.json()).then(fillForm).catch(() => {
  saveNote.className = "bad";
  saveNote.textContent = "Could not load settings";
});
refresh();
setInterval(refresh, 1000);
requestAnimationFrame(draw);
