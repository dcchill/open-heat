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

## How to Use

1. Connect your laptop to the WiFi network you want to measure.
2. Start the app.
3. Walk to a physical location.
4. Click the matching spot on the map to record the current signal.
5. Keep walking and clicking to build the heatmap.

Right-click a sample point or AP marker to remove it. Use **Save CSV** and **Load CSV** to move raw samples between tools.

The live panel shows details for the access point you are currently connected to, including BSSID, channel, radio type, security, link rates, and adapter name. New samples save the current AP details into the CSV.

## Survey Tools

Use **Auto sample at cursor** to record a reading every few seconds at the current mouse position on the map. Move the cursor along the floor plan as you walk. The **Auto interval seconds** slider controls the timing.

Use **Save session** and **Load session** to keep the full survey state, including samples, AP markers, floor plan path, and heatmap settings.

Use **Export image** to save the current floor plan, heatmap, samples, and AP markers as a dependency-free PPM image.

Use **Add AP marker** to place a visual AP label on the map. This is only a visual marker and does not affect signal calculations.

## Floor Plans

Use **Load floor plan** to place a PNG or GIF floor plan behind the heatmap. If you do not have one, the blank grid still works.

When **Keep heat inside black walls** is enabled, the app treats dark pixels in the floor plan as barriers. This keeps signal color from blending through black wall lines into a separate room. Use **Wall darkness** to tune how dark a pixel must be before it counts as a wall.

Wall blocking follows the actual floor plan pixels between each measured sample and each heatmap point. It does not require walls to line up with the heatmap cells. Use **Heat detail** to trade smoothness against redraw speed; smaller values draw a finer heatmap.

## Notes

Windows reports WiFi signal as a quality percentage. The app converts that to an approximate dBm value with a common formula:

```text
dBm = percent / 2 - 100
```

This is best for relative coverage mapping, not lab-grade RF measurement.
