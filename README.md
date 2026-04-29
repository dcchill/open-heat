# WiFi Heatmap Survey

A small Windows desktop tool for walking around a space and mapping live WiFi signal strength.

## Run

```powershell
python .\wifi_heatmap.py
```

No third-party packages are required. The app uses Python's built-in Tkinter UI and reads WiFi signal quality from:

```powershell
netsh wlan show interfaces
```

## Web UI Preview

There is also a local browser UI alternative:

```powershell
python .\webui_server.py
```

Then open:

```text
http://127.0.0.1:8765
```

The web UI keeps the existing no-dependency Python backend for live WiFi readings, but uses a browser
canvas for the map, heatmap, floor plan loading, CSV export, and session save/load. It is currently a
clean preview UI, not a full replacement for every Tkinter feature.

## How to Use

1. Connect your laptop to the WiFi network you want to measure.
2. Start the app.
3. Walk to a physical location.
4. Click the matching spot on the map to record the current signal.
5. Keep walking and clicking to build the heatmap.

Hover over an existing sample point to inspect its recorded SSID, BSSID, channel, RSSI, and timestamp. Drag a sample point to correct its map position. Right-click a sample point or AP marker to remove it. Use **Save CSV** and **Load CSV** to move raw samples between tools.

The live panel shows details for the access point you are currently connected to, including BSSID, channel, radio type, security, link rates, and adapter name. New samples save the current AP details into the CSV.

Use **Run ping/speed now** to test current internet latency and download throughput without adding a map sample. The ping host, download URL, and download size are configurable. By default, the app pings `1.1.1.1` and downloads a small Cloudflare speed-test payload.

Use **Run diagnostics report** in the desktop app, or **Run Diagnostics** in the web UI, to collect a troubleshooting snapshot. The report includes the current WiFi connection, ping and DNS checks, IP adapter details, and nearby WiFi networks discovered by Windows. Save the JSON report when you need to compare locations or share raw diagnostics.

Enable **Measure on new samples** to attach ping and download results to every new map sample. Samples are still placed immediately; the internet test runs in the background and updates the sample when it completes. Hover over a sample to inspect its saved internet result. **Save CSV** and **Save session** include these internet fields.

## Survey Tools

Use **Auto sample at cursor** to record a reading every few seconds at the current mouse position on the map. Move the cursor along the floor plan as you walk. The **Auto interval seconds** slider controls the timing.

Use **Save session** and **Load session** to keep the full survey state, including samples, AP markers, floor plan path, and heatmap settings.

Use **Export image** to save the current floor plan, heatmap, samples, and AP markers as a PNG image.

Use **Add AP marker** to place a visual AP label on the map. This is only a visual marker and does not affect signal calculations.

The coverage summary shows average, weakest, and strongest sampled RSSI, plus the estimated percentage of the mapped area below the weak-zone threshold. Use **Highlight weak zones** and **Weak-zone threshold dBm** to make low-coverage areas stand out.

Use the weak and strong color sliders to tune the heatmap color scale for your target environment.

## Floor Plans

Use **Load floor plan** to place a PNG or GIF floor plan behind the heatmap. If you do not have one, the blank grid still works.

When **Keep heat inside black walls** is enabled, the app treats dark pixels in the floor plan as barriers. This keeps signal color from blending through black wall lines into a separate room. Use **Wall darkness** to tune how dark a pixel must be before it counts as a wall.

Wall blocking follows the actual floor plan pixels between each measured sample and each heatmap point. It does not require walls to line up with the heatmap cells. Use **Heat detail** to trade smoothness against redraw speed; smaller values draw a finer heatmap.

Use **Set scale** to click two points with a known real-world distance. The app then shows approximate real-world cursor coordinates and draws a scale ruler on the map and exported image.

## Notes

Windows reports WiFi signal as a quality percentage. The app converts that to an approximate dBm value with a common formula:

```text
dBm = percent / 2 - 100
```

This is best for relative coverage mapping, not lab-grade RF measurement.
