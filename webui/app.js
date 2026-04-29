const MAP_W = 760;
const MAP_H = 620;

const state = {
  samples: [],
  apMarkers: [],
  current: null,
  floorPlan: null,
  floorPlanDataUrl: "",
  mouse: null,
  draggingIndex: null,
  dragMoved: false,
  pendingApName: "",
  scaleStart: null,
  pendingScale: false,
  scalePixels: null,
  scaleDistance: null,
  scaleUnit: "ft",
  autoTimer: null,
  wallMask: null,
  wallThreshold: null,
  lineWallCache: new Map(),
  lastDiagnostics: null,
};

const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");
const tooltip = document.getElementById("tooltip");
const els = Object.fromEntries([
  "status", "rssi", "signal", "count", "weakArea", "adapterDetails", "cellSize", "radius",
  "weakThreshold", "showWeak", "showGrid", "respectWalls", "wallThreshold", "weakColor",
  "strongColor", "addOnClick", "autoSample", "autoInterval", "measureOnSample", "pingHost",
  "downloadUrl", "downloadMb", "internetStatus", "dnsHost", "diagnosticsStatus",
  "diagnosticsReport", "coords", "scaleText",
].map((id) => [id, document.getElementById(id)]));

function signalColor(rssi) {
  let weak = Number(els.weakColor.value);
  let strong = Number(els.strongColor.value);
  if (strong <= weak) strong = weak + 1;
  const span = strong - weak;
  const stops = [
    [weak, [190, 35, 35]],
    [weak + span * 0.28, [232, 120, 42]],
    [weak + span * 0.46, [238, 204, 70]],
    [weak + span * 0.66, [108, 185, 90]],
    [strong, [36, 140, 68]],
  ];
  if (rssi <= stops[0][0]) return rgb(stops[0][1]);
  if (rssi >= stops[stops.length - 1][0]) return rgb(stops[stops.length - 1][1]);
  for (let i = 0; i < stops.length - 1; i += 1) {
    const [av, ac] = stops[i];
    const [bv, bc] = stops[i + 1];
    if (rssi >= av && rssi <= bv) {
      const t = (rssi - av) / (bv - av);
      return rgb(ac.map((value, index) => Math.round(value + (bc[index] - value) * t)));
    }
  }
  return "#888";
}

function rgb(parts) {
  return `rgb(${parts[0]}, ${parts[1]}, ${parts[2]})`;
}

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  ctx.setTransform((rect.width * dpr) / MAP_W, 0, 0, (rect.height * dpr) / MAP_H, 0, 0);
}

function draw() {
  resizeCanvas();
  state.lineWallCache.clear();
  ctx.clearRect(0, 0, MAP_W, MAP_H);
  ctx.fillStyle = "#fbfaf5";
  ctx.fillRect(0, 0, MAP_W, MAP_H);
  if (state.floorPlan) ctx.drawImage(state.floorPlan, 0, 0, MAP_W, MAP_H);
  if (els.showGrid.checked) drawGrid();
  drawHeatmap();
  drawSamples();
  drawApMarkers();
  drawScaleLine();
  updateStats();
  saveLocal();
}

function drawGrid() {
  ctx.strokeStyle = "#e1e6e2";
  ctx.lineWidth = 1;
  for (let x = 0; x <= MAP_W; x += 50) line(x, 0, x, MAP_H);
  for (let y = 0; y <= MAP_H; y += 50) line(0, y, MAP_W, y);
}

function line(x1, y1, x2, y2) {
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
}

function drawHeatmap() {
  if (state.samples.length === 0) {
    ctx.fillStyle = "#5f6a68";
    ctx.font = "16px Arial";
    ctx.textAlign = "center";
    ctx.fillText("Click the map to record the current WiFi strength", MAP_W / 2, MAP_H / 2);
    return;
  }
  if (els.respectWalls.checked && state.floorPlan) ensureWallMask();
  const cell = Number(els.cellSize.value);
  const radiusSq = Number(els.radius.value) ** 2;
  for (let y = 0; y < MAP_H; y += cell) {
    for (let x = 0; x < MAP_W; x += cell) {
      const cx = x + cell / 2;
      const cy = y + cell / 2;
      if (els.respectWalls.checked && state.floorPlan && isWallNear(cx, cy, Math.max(1, Math.floor(cell / 6)))) continue;
      const rssi = estimateRssi(cx, cy, radiusSq);
      if (rssi == null) continue;
      ctx.globalAlpha = 0.52;
      ctx.fillStyle = signalColor(rssi);
      ctx.fillRect(x, y, cell + 1, cell + 1);
      if (els.showWeak.checked && rssi <= Number(els.weakThreshold.value)) {
        ctx.globalAlpha = 0.9;
        ctx.strokeStyle = "#b33333";
        ctx.strokeRect(x + 1, y + 1, cell - 2, cell - 2);
      }
    }
  }
  ctx.globalAlpha = 1;
}

function estimateRssi(x, y, radiusSq) {
  let weighted = 0;
  let total = 0;
  const useWalls = els.respectWalls.checked && state.floorPlan;
  for (const sample of state.samples) {
    const dx = x - sample.x;
    const dy = y - sample.y;
    const distSq = dx * dx + dy * dy;
    if (distSq > radiusSq) continue;
    if (useWalls && lineCrossesWall(x, y, sample.x, sample.y)) continue;
    const weight = 1 / Math.max(1, distSq);
    weighted += sample.rssi_dbm * weight;
    total += weight;
  }
  return total > 0 ? weighted / total : null;
}

function drawSamples() {
  state.samples.forEach((sample, index) => {
    ctx.fillStyle = signalColor(sample.rssi_dbm);
    ctx.strokeStyle = "#172026";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(sample.x, sample.y, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#172026";
    ctx.font = "bold 9px Arial";
    ctx.textAlign = "center";
    ctx.fillText(String(index + 1), sample.x, sample.y - 16);
  });
}

function drawApMarkers() {
  for (const marker of state.apMarkers) {
    ctx.fillStyle = "#2f6fcf";
    ctx.strokeStyle = "#17345f";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(marker.x, marker.y - 13);
    ctx.lineTo(marker.x + 13, marker.y);
    ctx.lineTo(marker.x, marker.y + 13);
    ctx.lineTo(marker.x - 13, marker.y);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#fff";
    ctx.font = "bold 7px Arial";
    ctx.textAlign = "center";
    ctx.fillText("AP", marker.x, marker.y + 3);
    ctx.fillStyle = "#17345f";
    ctx.font = "bold 9px Arial";
    ctx.fillText(marker.name, marker.x, marker.y + 25);
  }
}

function drawScaleLine() {
  updateScaleText();
  if (!state.scalePixels || !state.scaleDistance) return;
  const length = Math.min(state.scalePixels, Math.max(60, MAP_W * 0.25));
  const x1 = 24;
  const y = MAP_H - 24;
  const x2 = x1 + length;
  const distance = length * state.scaleDistance / state.scalePixels;
  ctx.strokeStyle = "#202020";
  ctx.lineWidth = 3;
  line(x1, y, x2, y);
  ctx.lineWidth = 2;
  line(x1, y - 6, x1, y + 6);
  line(x2, y - 6, x2, y + 6);
  ctx.fillStyle = "#202020";
  ctx.font = "bold 9px Arial";
  ctx.textAlign = "center";
  ctx.fillText(`${distance.toFixed(1)} ${state.scaleUnit}`, (x1 + x2) / 2, y - 14);
}

function addSample(x, y) {
  if (!state.current || state.current.rssi_dbm == null) {
    els.status.textContent = "No WiFi reading available yet.";
    return;
  }
  const sample = {
    x: round1(x),
    y: round1(y),
    rssi_dbm: state.current.rssi_dbm,
    signal_percent: state.current.signal_percent,
    ssid: state.current.ssid || "",
    bssid: state.current.bssid || "",
    band: state.current.band || "",
    channel: state.current.channel || "",
    radio_type: state.current.radio_type || "",
    authentication: state.current.authentication || "",
    ping_ms: null,
    download_mbps: null,
    speed_tested_at: "",
    speed_error: "",
    created_at: timestamp(),
  };
  state.samples.push(sample);
  if (els.measureOnSample.checked) runInternetTest(sample);
  draw();
}

function round1(value) {
  return Math.round(value * 10) / 10;
}

function timestamp() {
  return new Date().toISOString().slice(0, 19).replace("T", " ");
}

async function runInternetTest(sample = null) {
  els.internetStatus.textContent = sample ? "Internet test running for sample..." : "Internet test running...";
  try {
    const response = await fetch("/api/internet", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ping_host: els.pingHost.value.trim(),
        download_url: els.downloadUrl.value.trim(),
        download_bytes: Math.max(1, Number(els.downloadMb.value)) * 1_000_000,
      }),
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`HTTP ${response.status}: ${text.slice(0, 80).trim()}`);
    }
    const result = await response.json();
    if (sample) Object.assign(sample, result);
    const parts = [];
    if (result.ping_ms != null) parts.push(`Ping ${Math.round(result.ping_ms)} ms`);
    if (result.download_mbps != null) parts.push(`Down ${result.download_mbps.toFixed(1)} Mbps`);
    if (result.speed_error) parts.push(`Error: ${result.speed_error}`);
    els.internetStatus.textContent = `Internet test:\n${parts.join(" | ") || "No result"}`;
    draw();
  } catch (error) {
    els.internetStatus.textContent = `Internet test error: ${error.message}`;
  }
}

async function runDiagnostics() {
  els.diagnosticsStatus.textContent = "Diagnostics running...";
  els.diagnosticsReport.innerHTML = "";
  try {
    const response = await fetch("/api/diagnostics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ping_host: els.pingHost.value.trim(),
        dns_host: els.dnsHost.value.trim(),
      }),
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`HTTP ${response.status}: ${text.slice(0, 80).trim()}`);
    }
    state.lastDiagnostics = await response.json();
    els.diagnosticsStatus.textContent = `Diagnostics: ${state.lastDiagnostics.created_at || "complete"}`;
    renderDiagnostics(state.lastDiagnostics);
  } catch (error) {
    els.diagnosticsStatus.textContent = `Diagnostics error: ${error.message}`;
  }
}

function renderDiagnostics(report) {
  const checks = report.checks || [];
  const adapters = report.ip_adapters || [];
  const networks = report.nearby_networks || [];
  const wifi = report.wifi || {};
  const connected = [
    ["SSID", wifi.ssid || "(hidden)"],
    ["BSSID", wifi.bssid],
    ["State", wifi.state],
    ["RSSI", wifi.rssi_dbm == null ? "" : `${wifi.rssi_dbm} dBm`],
    ["Signal", wifi.signal_percent == null ? "" : `${wifi.signal_percent}%`],
    ["Channel", wifi.channel],
    ["Link", `${wifi.receive_rate || "-"} / ${wifi.transmit_rate || "-"} Mbps`],
  ];
  els.diagnosticsReport.innerHTML = `
    <h3>Connection</h3>
    <dl>${connected.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value || "-")}</dd>`).join("")}</dl>
    <h3>Checks</h3>
    <ul>${checks.map((check) => `<li class="${check.ok ? "ok" : "bad"}"><strong>${escapeHtml(check.name)}</strong><span>${escapeHtml(check.detail || "-")}</span></li>`).join("") || "<li>No checks returned.</li>"}</ul>
    <h3>IP Adapters</h3>
    <ul>${adapters.map((adapter) => `<li><strong>${escapeHtml(adapter.name)}</strong><span>IPv4 ${escapeHtml((adapter.ipv4 || []).join(", ") || "-")} | Gateway ${escapeHtml((adapter.gateway || []).join(", ") || "-")} | DNS ${escapeHtml((adapter.dns || []).join(", ") || "-")}</span></li>`).join("") || "<li>No adapter details returned.</li>"}</ul>
    <h3>Nearby Networks</h3>
    <ul>${networks.map((network) => `<li><strong>${escapeHtml(network.ssid || "(hidden)")}</strong><span>${escapeHtml(network.bssid_count)} BSSID | ${escapeHtml(network.strongest_signal_percent ?? "-")}% | Ch ${escapeHtml((network.channels || []).join(", ") || "-")} | ${escapeHtml(network.authentication || "-")}</span></li>`).join("") || "<li>No nearby networks returned.</li>"}</ul>
  `;
}

function exportDiagnostics() {
  if (!state.lastDiagnostics) {
    els.diagnosticsStatus.textContent = "Diagnostics: run a report first.";
    return;
  }
  download("open-heat-diagnostics.json", "application/json", JSON.stringify(state.lastDiagnostics, null, 2));
}

function updateStats() {
  els.count.textContent = String(state.samples.length);
  if (state.samples.length === 0) {
    els.weakArea.textContent = "-";
    return;
  }
  const rssis = state.samples.map((sample) => sample.rssi_dbm);
  const weakCount = rssis.filter((value) => value <= Number(els.weakThreshold.value)).length;
  els.weakArea.textContent = `${Math.round((weakCount / rssis.length) * 100)}%`;
}

async function pollWifi() {
  try {
    const response = await fetch("/api/wifi", { cache: "no-store" });
    state.current = await response.json();
    els.rssi.textContent = state.current.rssi_dbm == null ? "-" : `${state.current.rssi_dbm}`;
    els.signal.textContent = state.current.signal_percent == null ? "-" : `${state.current.signal_percent}%`;
    els.status.textContent = state.current.signal_percent == null
      ? "No WiFi reading\nWindows WiFi required"
      : `${state.current.ssid || "(hidden)"}\n${state.current.bssid || "-"} | Ch ${state.current.channel || "-"}`;
    renderDetails();
  } catch {
    els.status.textContent = "Web UI server is not responding.";
  }
  setTimeout(pollWifi, 1500);
}

function renderDetails() {
  const rows = [
    ["Adapter", state.current.adapter],
    ["State", state.current.state],
    ["Band", state.current.band],
    ["Channel", state.current.channel],
    ["Radio", state.current.radio_type],
    ["Security", state.current.authentication],
    ["Cipher", state.current.cipher],
    ["Link", `${state.current.receive_rate || "-"} / ${state.current.transmit_rate || "-"} Mbps`],
  ];
  els.adapterDetails.innerHTML = rows.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value || "-")}</dd>`).join("");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
}

function ensureWallMask() {
  const threshold = Number(els.wallThreshold.value);
  if (!state.floorPlan || state.wallMask?.threshold === threshold) return;
  const offscreen = document.createElement("canvas");
  offscreen.width = MAP_W;
  offscreen.height = MAP_H;
  const offCtx = offscreen.getContext("2d");
  offCtx.drawImage(state.floorPlan, 0, 0, MAP_W, MAP_H);
  const data = offCtx.getImageData(0, 0, MAP_W, MAP_H).data;
  const mask = new Uint8Array(MAP_W * MAP_H);
  for (let i = 0; i < mask.length; i += 1) {
    const offset = i * 4;
    const dark = (data[offset] + data[offset + 1] + data[offset + 2]) / 3;
    mask[i] = dark <= threshold && data[offset + 3] > 20 ? 1 : 0;
  }
  state.wallMask = { threshold, mask };
}

function isWallNear(x, y, radius) {
  ensureWallMask();
  if (!state.wallMask) return false;
  const cx = Math.round(x);
  const cy = Math.round(y);
  for (let dy = -radius; dy <= radius; dy += 1) {
    for (let dx = -radius; dx <= radius; dx += 1) {
      if (isWallPixel(cx + dx, cy + dy)) return true;
    }
  }
  return false;
}

function lineCrossesWall(x1, y1, x2, y2) {
  ensureWallMask();
  if (!state.wallMask) return false;
  const key = `${Math.round(x1)},${Math.round(y1)},${Math.round(x2)},${Math.round(y2)},${state.wallMask.threshold}`;
  if (state.lineWallCache.has(key)) return state.lineWallCache.get(key);
  const steps = Math.max(1, Math.ceil(Math.hypot(x2 - x1, y2 - y1)));
  for (let i = 0; i <= steps; i += 4) {
    const t = i / steps;
    if (isWallPixel(Math.round(x1 + (x2 - x1) * t), Math.round(y1 + (y2 - y1) * t))) {
      state.lineWallCache.set(key, true);
      return true;
    }
  }
  state.lineWallCache.set(key, false);
  return false;
}

function isWallPixel(x, y) {
  if (!state.wallMask || x < 0 || y < 0 || x >= MAP_W || y >= MAP_H) return false;
  return state.wallMask.mask[y * MAP_W + x] === 1;
}

function mapPoint(event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) / rect.width) * MAP_W,
    y: ((event.clientY - rect.top) / rect.height) * MAP_H,
  };
}

function nearestSample(x, y, maxDistance = 14) {
  let best = null;
  let bestDistance = maxDistance;
  state.samples.forEach((sample, index) => {
    const distance = Math.hypot(sample.x - x, sample.y - y);
    if (distance <= bestDistance) {
      best = index;
      bestDistance = distance;
    }
  });
  return best;
}

function nearestAp(x, y, maxDistance = 18) {
  let best = null;
  let bestDistance = maxDistance;
  state.apMarkers.forEach((marker, index) => {
    const distance = Math.hypot(marker.x - x, marker.y - y);
    if (distance <= bestDistance) {
      best = index;
      bestDistance = distance;
    }
  });
  return best;
}

function sampleText(sample) {
  return [
    `RSSI: ${sample.rssi_dbm} dBm | Signal: ${sample.signal_percent || "-"}%`,
    `SSID: ${sample.ssid || "(hidden)"}`,
    `BSSID: ${sample.bssid || "-"}`,
    `Channel: ${sample.channel || "-"} | Band: ${sample.band || "-"}`,
    `Created: ${sample.created_at || "-"}`,
    sample.ping_ms != null || sample.download_mbps != null || sample.speed_error
      ? `Ping: ${formatOptional(sample.ping_ms, " ms")} | Download: ${formatOptional(sample.download_mbps, " Mbps", 1)}${sample.speed_error ? `\nSpeed error: ${sample.speed_error}` : ""}`
      : "",
  ].filter(Boolean).join("\n");
}

function formatOptional(value, suffix = "", precision = 0) {
  return value == null ? "-" : `${Number(value).toFixed(precision)}${suffix}`;
}

function updateCoords(point) {
  if (!point) {
    els.coords.textContent = "x: -, y: -";
    return;
  }
  let text = `x: ${Math.round(point.x)}, y: ${Math.round(point.y)}`;
  if (state.scalePixels && state.scaleDistance) {
    text += ` | ${((point.x * state.scaleDistance) / state.scalePixels).toFixed(1)} ${state.scaleUnit}, ${((point.y * state.scaleDistance) / state.scalePixels).toFixed(1)} ${state.scaleUnit}`;
  }
  els.coords.textContent = text;
}

function updateScaleText() {
  els.scaleText.textContent = state.scalePixels && state.scaleDistance
    ? `Scale: ${Number(state.scaleDistance).toPrecision(4).replace(/\.?0+$/, "")} ${state.scaleUnit} = ${state.scalePixels.toFixed(1)} px`
    : "Scale: not set";
}

function exportCsv() {
  const header = ["x", "y", "rssi_dbm", "signal_percent", "ssid", "bssid", "band", "channel", "radio_type", "authentication", "ping_ms", "download_mbps", "speed_tested_at", "speed_error", "created_at"];
  const rows = state.samples.map((sample) => header.map((key) => csvCell(sample[key] ?? "")).join(","));
  download("open-heat-web-samples.csv", "text/csv", [header.join(","), ...rows].join("\n"));
}

function csvCell(value) {
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') {
        cell += '"';
        i += 1;
      } else if (char === '"') quoted = false;
      else cell += char;
    } else if (char === '"') quoted = true;
    else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (char !== "\r") cell += char;
  }
  row.push(cell);
  rows.push(row);
  const header = rows.shift() || [];
  return rows.filter((item) => item.length > 1).map((item) => normalizeSample(Object.fromEntries(header.map((key, index) => [key, item[index] ?? ""]))));
}

function normalizeSample(item) {
  return {
    x: Number(item.x || 0),
    y: Number(item.y || 0),
    rssi_dbm: Number(item.rssi_dbm || -100),
    signal_percent: item.signal_percent ?? "",
    ssid: item.ssid || "",
    bssid: item.bssid || "",
    band: item.band || "",
    channel: item.channel || "",
    radio_type: item.radio_type || "",
    authentication: item.authentication || "",
    ping_ms: item.ping_ms === "" || item.ping_ms == null ? null : Number(item.ping_ms),
    download_mbps: item.download_mbps === "" || item.download_mbps == null ? null : Number(item.download_mbps),
    speed_tested_at: item.speed_tested_at || "",
    speed_error: item.speed_error || "",
    created_at: item.created_at || timestamp(),
  };
}

function sessionData() {
  return {
    floorplan_data_url: state.floorPlanDataUrl,
    floorplan_path: null,
    settings: {
      show_grid: els.showGrid.checked,
      respect_walls: els.respectWalls.checked,
      cell_size: Number(els.cellSize.value),
      max_radius: Number(els.radius.value),
      wall_threshold: Number(els.wallThreshold.value),
      auto_interval: Number(els.autoInterval.value),
      show_weak_zones: els.showWeak.checked,
      color_weak: Number(els.weakColor.value),
      color_strong: Number(els.strongColor.value),
      weak_zone_threshold: Number(els.weakThreshold.value),
      measure_internet_on_sample: els.measureOnSample.checked,
      ping_host: els.pingHost.value,
      download_url: els.downloadUrl.value,
      download_megabytes: Number(els.downloadMb.value),
    },
    scale: { pixels: state.scalePixels, distance: state.scaleDistance, unit: state.scaleUnit },
    samples: state.samples,
    ap_markers: state.apMarkers,
  };
}

function loadSession(data) {
  const settings = data.settings || {};
  els.showGrid.checked = settings.show_grid ?? els.showGrid.checked;
  els.respectWalls.checked = settings.respect_walls ?? els.respectWalls.checked;
  els.cellSize.value = settings.cell_size ?? els.cellSize.value;
  els.radius.value = settings.max_radius ?? els.radius.value;
  els.wallThreshold.value = settings.wall_threshold ?? els.wallThreshold.value;
  els.autoInterval.value = settings.auto_interval ?? els.autoInterval.value;
  els.showWeak.checked = settings.show_weak_zones ?? els.showWeak.checked;
  els.weakColor.value = settings.color_weak ?? els.weakColor.value;
  els.strongColor.value = settings.color_strong ?? els.strongColor.value;
  els.weakThreshold.value = settings.weak_zone_threshold ?? els.weakThreshold.value;
  els.measureOnSample.checked = settings.measure_internet_on_sample ?? els.measureOnSample.checked;
  els.pingHost.value = settings.ping_host ?? els.pingHost.value;
  els.downloadUrl.value = settings.download_url ?? els.downloadUrl.value;
  els.downloadMb.value = settings.download_megabytes ?? els.downloadMb.value;
  const scale = data.scale || {};
  state.scalePixels = scale.pixels || null;
  state.scaleDistance = scale.distance || null;
  state.scaleUnit = scale.unit || "ft";
  state.samples = (data.samples || []).map(normalizeSample);
  state.apMarkers = (data.ap_markers || []).map((marker) => ({ x: Number(marker.x || 0), y: Number(marker.y || 0), name: marker.name || "AP" }));
  if (data.floorplan_data_url) loadFloorPlan(data.floorplan_data_url);
  else {
    state.floorPlan = null;
    state.floorPlanDataUrl = "";
  }
  draw();
}

function download(name, type, contents) {
  const blob = new Blob([contents], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function exportPng() {
  draw();
  canvas.toBlob((blob) => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "open-heat-map.png";
    link.click();
    URL.revokeObjectURL(url);
  }, "image/png");
}

function saveLocal() {
  try {
    localStorage.setItem("openHeatWebUi", JSON.stringify(sessionData()));
  } catch {
    // Ignore storage errors in private browsing.
  }
}

function loadFloorPlan(dataUrl) {
  const image = new Image();
  image.onload = () => {
    state.floorPlan = image;
    state.floorPlanDataUrl = dataUrl;
    state.wallMask = null;
    draw();
  };
  image.src = dataUrl;
}

canvas.addEventListener("pointerdown", (event) => {
  const point = mapPoint(event);
  if (state.pendingScale) {
    handleScaleClick(point);
    return;
  }
  if (state.pendingApName) {
    state.apMarkers.push({ x: point.x, y: point.y, name: state.pendingApName });
    state.pendingApName = "";
    draw();
    return;
  }
  const index = nearestSample(point.x, point.y);
  if (index != null) {
    state.draggingIndex = index;
    state.dragMoved = false;
    canvas.setPointerCapture(event.pointerId);
    return;
  }
  if (els.addOnClick.checked) addSample(point.x, point.y);
});

canvas.addEventListener("pointermove", (event) => {
  const point = mapPoint(event);
  state.mouse = point;
  updateCoords(point);
  if (state.draggingIndex != null) {
    const sample = state.samples[state.draggingIndex];
    sample.x = point.x;
    sample.y = point.y;
    state.dragMoved = true;
    draw();
    return;
  }
  const index = nearestSample(point.x, point.y);
  if (index != null) {
    tooltip.hidden = false;
    tooltip.textContent = sampleText(state.samples[index]);
    tooltip.style.left = `${event.clientX + 14}px`;
    tooltip.style.top = `${event.clientY + 14}px`;
  } else {
    tooltip.hidden = true;
  }
});

canvas.addEventListener("pointerup", () => {
  state.draggingIndex = null;
});

canvas.addEventListener("mouseleave", () => {
  state.mouse = null;
  tooltip.hidden = true;
  updateCoords(null);
});

canvas.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  const point = mapPoint(event);
  const sample = nearestSample(point.x, point.y, 18);
  if (sample != null) state.samples.splice(sample, 1);
  else {
    const marker = nearestAp(point.x, point.y, 22);
    if (marker != null) state.apMarkers.splice(marker, 1);
  }
  draw();
});

function handleScaleClick(point) {
  if (!state.scaleStart) {
    state.scaleStart = point;
    els.scaleText.textContent = "Click the second scale point.";
    return;
  }
  const pixels = Math.hypot(point.x - state.scaleStart.x, point.y - state.scaleStart.y);
  const distance = Number(prompt("Known real-world distance:", "10"));
  if (!distance || distance <= 0) {
    state.pendingScale = false;
    state.scaleStart = null;
    return;
  }
  state.scalePixels = pixels;
  state.scaleDistance = distance;
  state.scaleUnit = (prompt("Unit label:", state.scaleUnit) || state.scaleUnit || "ft").trim();
  state.pendingScale = false;
  state.scaleStart = null;
  draw();
}

document.getElementById("addCenter").addEventListener("click", () => addSample(MAP_W / 2, MAP_H / 2));
document.getElementById("undo").addEventListener("click", () => {
  state.samples.pop();
  draw();
});
document.getElementById("clear").addEventListener("click", () => {
  if (confirm("Remove all samples?")) {
    state.samples = [];
    draw();
  }
});
document.getElementById("runInternet").addEventListener("click", () => runInternetTest());
document.getElementById("runDiagnostics").addEventListener("click", runDiagnostics);
document.getElementById("exportDiagnostics").addEventListener("click", exportDiagnostics);
document.getElementById("setScale").addEventListener("click", () => {
  state.pendingScale = true;
  state.scaleStart = null;
  els.scaleText.textContent = "Click the first scale point.";
});
document.getElementById("clearScale").addEventListener("click", () => {
  state.scalePixels = null;
  state.scaleDistance = null;
  state.scaleStart = null;
  state.pendingScale = false;
  draw();
});
document.getElementById("addAp").addEventListener("click", () => {
  state.pendingApName = prompt("AP marker name:", `AP ${state.apMarkers.length + 1}`) || "";
});
document.getElementById("clearAp").addEventListener("click", () => {
  if (confirm("Remove all AP markers?")) {
    state.apMarkers = [];
    draw();
  }
});
document.getElementById("exportCsv").addEventListener("click", exportCsv);
document.getElementById("exportJson").addEventListener("click", () => download("open-heat-web-session.json", "application/json", JSON.stringify(sessionData(), null, 2)));
document.getElementById("exportPng").addEventListener("click", exportPng);
document.getElementById("clearFloor").addEventListener("click", () => {
  state.floorPlan = null;
  state.floorPlanDataUrl = "";
  state.wallMask = null;
  draw();
});
document.getElementById("floorPlan").addEventListener("change", (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => loadFloorPlan(reader.result);
  reader.readAsDataURL(file);
});
document.getElementById("loadJson").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (file) loadSession(JSON.parse(await file.text()));
});
document.getElementById("loadCsv").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  state.samples = parseCsv(await file.text());
  draw();
});
els.autoSample.addEventListener("change", () => {
  if (state.autoTimer) clearInterval(state.autoTimer);
  state.autoTimer = null;
  if (els.autoSample.checked) {
    state.autoTimer = setInterval(() => {
      if (state.mouse) addSample(state.mouse.x, state.mouse.y);
    }, Math.max(2, Number(els.autoInterval.value)) * 1000);
  }
});

[
  els.cellSize, els.radius, els.weakThreshold, els.showWeak, els.showGrid, els.respectWalls,
  els.wallThreshold, els.weakColor, els.strongColor,
].forEach((input) => input.addEventListener("input", () => {
  state.wallMask = null;
  draw();
}));
window.addEventListener("resize", draw);

try {
  const saved = JSON.parse(localStorage.getItem("openHeatWebUi") || "null");
  if (saved) loadSession(saved);
} catch {
  draw();
}

draw();
pollWifi();
