import csv
import json
import math
import re
import subprocess
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog


WIDTH = 1000
HEIGHT = 680
MAP_W = 760
MAP_H = 620
POLL_MS = 1500


class WifiReading:
    def __init__(
        self,
        ssid="",
        bssid="",
        signal_percent=None,
        rssi_dbm=None,
        adapter="",
        state="",
        radio_type="",
        authentication="",
        cipher="",
        channel="",
        band="",
        receive_rate="",
        transmit_rate="",
        profile="",
    ):
        self.ssid = ssid
        self.bssid = bssid
        self.signal_percent = signal_percent
        self.rssi_dbm = rssi_dbm
        self.adapter = adapter
        self.state = state
        self.radio_type = radio_type
        self.authentication = authentication
        self.cipher = cipher
        self.channel = channel
        self.band = band
        self.receive_rate = receive_rate
        self.transmit_rate = transmit_rate
        self.profile = profile


class Sample:
    def __init__(
        self,
        x,
        y,
        rssi,
        ssid,
        signal_percent,
        created_at=None,
        bssid="",
        channel="",
        band="",
        radio_type="",
        authentication="",
    ):
        self.x = float(x)
        self.y = float(y)
        self.rssi = float(rssi)
        self.ssid = ssid
        self.signal_percent = signal_percent
        self.created_at = created_at or time.strftime("%Y-%m-%d %H:%M:%S")
        self.bssid = bssid
        self.channel = channel
        self.band = band
        self.radio_type = radio_type
        self.authentication = authentication


class APMarker:
    def __init__(self, x, y, name):
        self.x = float(x)
        self.y = float(y)
        self.name = name


def signal_percent_to_dbm(percent):
    if percent is None:
        return None
    percent = max(0, min(100, int(percent)))
    # Windows reports signal quality, not raw RSSI. This common approximation
    # gives a useful relative value for walking surveys.
    return round((percent / 2.0) - 100)


def read_wifi():
    if sys.platform != "win32":
        return WifiReading()

    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return WifiReading()

    output = result.stdout
    if not output.strip():
        return WifiReading()

    def field(name):
        match = re.search(rf"^\s*{re.escape(name)}\s*:\s*(.*?)\s*$", output, re.I | re.M)
        return match.group(1).strip() if match else ""

    signal_text = field("Signal")
    percent = None
    match = re.search(r"(\d+)\s*%", signal_text)
    if match:
        percent = int(match.group(1))

    rssi_dbm = signal_percent_to_dbm(percent)
    rssi_text = field("Rssi") or field("RSSI")
    match = re.search(r"-?\d+", rssi_text)
    if match:
        rssi_dbm = int(match.group(0))

    return WifiReading(
        ssid=field("SSID"),
        bssid=field("AP BSSID") or field("BSSID"),
        signal_percent=percent,
        rssi_dbm=rssi_dbm,
        adapter=field("Name"),
        state=field("State"),
        radio_type=field("Radio type"),
        authentication=field("Authentication"),
        cipher=field("Cipher"),
        channel=field("Channel"),
        band=field("Band"),
        receive_rate=field("Receive rate (Mbps)"),
        transmit_rate=field("Transmit rate (Mbps)"),
        profile=field("Profile"),
    )


def rssi_color(rssi):
    # Red/orange means weak, yellow is moderate, green is strong.
    stops = [
        (-90, (190, 35, 35)),
        (-75, (232, 120, 42)),
        (-65, (238, 204, 70)),
        (-55, (108, 185, 90)),
        (-35, (36, 140, 68)),
    ]
    if rssi <= stops[0][0]:
        return rgb(stops[0][1])
    if rssi >= stops[-1][0]:
        return rgb(stops[-1][1])

    for (a_value, a_color), (b_value, b_color) in zip(stops, stops[1:]):
        if a_value <= rssi <= b_value:
            t = (rssi - a_value) / (b_value - a_value)
            return rgb(tuple(round(a + (b - a) * t) for a, b in zip(a_color, b_color)))
    return "#888888"


def rgb(values):
    return "#{:02x}{:02x}{:02x}".format(*values)


def color_to_tuple(color):
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


class HeatmapApp:
    def __init__(self, root):
        self.root = root
        self.root.title("WiFi Heatmap Survey")
        self.samples = []
        self.ap_markers = []
        self.current = WifiReading()
        self.selected_sample = None
        self.last_mouse = None
        self.pending_ap_name = None
        self.add_on_click = tk.BooleanVar(value=True)
        self.show_grid = tk.BooleanVar(value=True)
        self.respect_walls = tk.BooleanVar(value=True)
        self.auto_sample = tk.BooleanVar(value=False)
        self.cell_size = tk.IntVar(value=18)
        self.max_radius = tk.IntVar(value=180)
        self.wall_threshold = tk.IntVar(value=95)
        self.auto_interval = tk.IntVar(value=5)
        self.floorplan = None
        self.floorplan_path = None
        self.wall_mask = None
        self.wall_mask_threshold = None
        self.wall_line_cache = {}
        self.redraw_after_id = None
        self.auto_after_id = None

        self.build_ui()
        self.poll_wifi()
        self.draw()

    def build_ui(self):
        self.root.geometry(f"{WIDTH}x{HEIGHT}")
        self.root.minsize(900, 610)

        self.canvas = tk.Canvas(self.root, bg="#f7f7f3", highlightthickness=0, cursor="crosshair")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<Button-3>", self.on_canvas_right_click)
        self.canvas.bind("<Motion>", self.on_mouse_move)

        sidebar = tk.Frame(self.root, bg="#efeee8")
        sidebar.grid(row=0, column=1, sticky="nsew")
        self.sidebar_canvas = tk.Canvas(sidebar, bg="#efeee8", highlightthickness=0, width=250)
        scrollbar = tk.Scrollbar(sidebar, orient="vertical", command=self.sidebar_canvas.yview)
        self.sidebar_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.sidebar_canvas.pack(side="left", fill="both", expand=True)

        panel = tk.Frame(self.sidebar_canvas, padx=10, pady=10, bg="#efeee8")
        panel_window = self.sidebar_canvas.create_window((0, 0), window=panel, anchor="nw")
        panel.bind("<Configure>", lambda event: self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox("all")))
        self.sidebar_canvas.bind("<Configure>", lambda event: self.sidebar_canvas.itemconfigure(panel_window, width=event.width))
        self.sidebar_canvas.bind("<Enter>", lambda event: self.sidebar_canvas.bind_all("<MouseWheel>", self.on_sidebar_mousewheel))
        self.sidebar_canvas.bind("<Leave>", lambda event: self.sidebar_canvas.unbind_all("<MouseWheel>"))

        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, minsize=260)
        self.root.rowconfigure(0, weight=1)

        self.status = tk.StringVar(value="Reading WiFi...")
        self.coords = tk.StringVar(value="x: -, y: -")
        self.sample_count = tk.StringVar(value="Samples: 0")

        def section(text):
            tk.Label(panel, text=text, font=("Segoe UI", 10, "bold"), bg="#efeee8", fg="#39362f").pack(anchor="w", pady=(10, 2))

        section("Live Signal")
        tk.Label(panel, textvariable=self.status, justify="left", bg="#efeee8", wraplength=220).pack(anchor="w", pady=(2, 6))
        tk.Label(panel, textvariable=self.coords, bg="#efeee8").pack(anchor="w")
        tk.Label(panel, textvariable=self.sample_count, bg="#efeee8").pack(anchor="w", pady=(0, 6))

        section("Sampling")
        tk.Checkbutton(panel, text="Add sample on left click", variable=self.add_on_click, bg="#efeee8").pack(anchor="w")
        tk.Checkbutton(panel, text="Auto sample at cursor", variable=self.auto_sample, command=self.toggle_auto_sample, bg="#efeee8").pack(anchor="w")
        tk.Label(panel, text="Auto interval seconds", bg="#efeee8").pack(anchor="w")
        tk.Scale(panel, from_=2, to=30, orient="horizontal", variable=self.auto_interval, bg="#efeee8").pack(fill="x")

        section("Heatmap")
        tk.Checkbutton(panel, text="Show grid", variable=self.show_grid, command=self.schedule_draw, bg="#efeee8").pack(anchor="w")
        tk.Checkbutton(panel, text="Keep heat inside black walls", variable=self.respect_walls, command=self.schedule_draw, bg="#efeee8").pack(anchor="w")
        tk.Label(panel, text="Heat detail", bg="#efeee8").pack(anchor="w")
        tk.Scale(panel, from_=6, to=60, orient="horizontal", variable=self.cell_size, command=lambda _=None: self.schedule_draw(), bg="#efeee8").pack(fill="x")
        tk.Label(panel, text="Blend radius", bg="#efeee8").pack(anchor="w")
        tk.Scale(panel, from_=60, to=320, orient="horizontal", variable=self.max_radius, command=lambda _=None: self.schedule_draw(), bg="#efeee8").pack(fill="x")
        tk.Label(panel, text="Wall darkness", bg="#efeee8").pack(anchor="w")
        tk.Scale(panel, from_=35, to=180, orient="horizontal", variable=self.wall_threshold, command=lambda _=None: self.schedule_draw(invalidate_walls=True), bg="#efeee8").pack(fill="x")

        section("Actions")
        buttons = [
            ("Add at center", self.add_center_sample),
            ("Undo last", self.undo_sample),
            ("Clear samples", self.clear_samples),
            ("Add AP marker", self.begin_add_ap_marker),
            ("Clear AP markers", self.clear_ap_markers),
        ]
        for text, command in buttons:
            tk.Button(panel, text=text, command=command).pack(fill="x", pady=2)

        section("Files")
        file_buttons = [
            ("Save CSV", self.save_csv),
            ("Load CSV", self.load_csv),
            ("Save session", self.save_session),
            ("Load session", self.load_session),
            ("Export image", self.export_image),
            ("Load floor plan", self.load_floorplan),
            ("Clear floor plan", self.clear_floorplan),
        ]
        for text, command in file_buttons:
            tk.Button(panel, text=text, command=command).pack(fill="x", pady=2)

        tk.Label(
            panel,
            text="Walk to a spot, click its matching place on the map, then keep walking. Right click removes the nearest sample or AP marker.",
            bg="#efeee8",
            justify="left",
            wraplength=220,
        ).pack(anchor="w", pady=(10, 0))

    def poll_wifi(self):
        self.current = read_wifi()
        if self.current.signal_percent is None:
            text = "No WiFi reading\nWindows WiFi required"
        else:
            text = (
                f"SSID: {self.current.ssid or '(hidden)'}\n"
                f"BSSID: {self.current.bssid or '-'}\n"
                f"Signal: {self.current.signal_percent}%\n"
                f"RSSI: {self.current.rssi_dbm} dBm\n"
                f"Band/channel: {self.current.band or '-'} / {self.current.channel or '-'}\n"
                f"Radio: {self.current.radio_type or '-'}\n"
                f"Security: {self.current.authentication or '-'} / {self.current.cipher or '-'}\n"
                f"Link: {self.current.receive_rate or '-'} down, {self.current.transmit_rate or '-'} up Mbps\n"
                f"Adapter: {self.current.adapter or '-'}"
            )
        self.status.set(text)
        self.root.after(POLL_MS, self.poll_wifi)

    def on_sidebar_mousewheel(self, event):
        self.sidebar_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def toggle_auto_sample(self):
        if self.auto_sample.get():
            self.run_auto_sample()
        elif self.auto_after_id is not None:
            self.root.after_cancel(self.auto_after_id)
            self.auto_after_id = None

    def run_auto_sample(self):
        self.auto_after_id = None
        if not self.auto_sample.get():
            return
        target = self.last_mouse
        if target is not None and self.current.rssi_dbm is not None:
            self.add_sample(target[0], target[1], redraw=True, warn=False)
        delay = max(1, self.auto_interval.get()) * 1000
        self.auto_after_id = self.root.after(delay, self.run_auto_sample)

    def schedule_draw(self, invalidate_walls=False):
        if invalidate_walls:
            self.invalidate_wall_cache()
        if self.redraw_after_id is not None:
            self.root.after_cancel(self.redraw_after_id)
        self.redraw_after_id = self.root.after(80, self.draw)

    def canvas_bounds(self):
        width = max(self.canvas.winfo_width(), MAP_W)
        height = max(self.canvas.winfo_height(), MAP_H)
        return 20, 20, width - 20, height - 20

    def draw(self):
        self.redraw_after_id = None
        self.canvas.delete("all")
        self.wall_line_cache.clear()
        left, top, right, bottom = self.canvas_bounds()

        self.canvas.create_rectangle(left, top, right, bottom, fill="#fbfaf5", outline="#c9c5b8")
        if self.floorplan:
            self.canvas.create_image(left, top, image=self.floorplan, anchor="nw")

        if self.show_grid.get():
            self.draw_grid(left, top, right, bottom)

        self.draw_heatmap(left, top, right, bottom)
        self.draw_samples()
        self.draw_ap_markers()
        self.draw_legend(right - 180, bottom - 74)
        self.sample_count.set(f"Samples: {len(self.samples)} | APs: {len(self.ap_markers)}")

    def draw_grid(self, left, top, right, bottom):
        step = 50
        for x in range(int(left), int(right), step):
            self.canvas.create_line(x, top, x, bottom, fill="#e6e1d4")
        for y in range(int(top), int(bottom), step):
            self.canvas.create_line(left, y, right, y, fill="#e6e1d4")

    def draw_heatmap(self, left, top, right, bottom):
        if not self.samples:
            self.canvas.create_text(
                (left + right) / 2,
                (top + bottom) / 2,
                text="Click the map to record the current WiFi strength",
                fill="#5f5b50",
                font=("Segoe UI", 16),
            )
            return

        step = self.cell_size.get()
        radius = self.max_radius.get()
        radius_squared = radius * radius
        samples = [(sample.x, sample.y, sample.rssi) for sample in self.samples]
        use_walls = self.respect_walls.get() and self.floorplan is not None
        if use_walls:
            self.ensure_wall_mask()

        for x in range(int(left), int(right), step):
            for y in range(int(top), int(bottom), step):
                center_x = x + step / 2
                center_y = y + step / 2
                if use_walls and self.is_wall_near(center_x, center_y, max(1, step // 6)):
                    continue
                rssi = self.estimate_rssi(center_x, center_y, radius_squared, samples, use_walls)
                if rssi is None:
                    continue
                color = rssi_color(rssi)
                self.canvas.create_rectangle(x, y, x + step, y + step, fill=color, outline=color, stipple="gray50")

    def estimate_rssi(self, x, y, radius_squared, samples, use_walls):
        weighted_sum = 0.0
        weight_total = 0.0
        for sample_x, sample_y, sample_rssi in samples:
            dx = sample_x - x
            dy = sample_y - y
            distance_squared = dx * dx + dy * dy
            if distance_squared > radius_squared:
                continue
            if use_walls and self.line_crosses_wall(x, y, sample_x, sample_y):
                continue
            distance = math.sqrt(distance_squared)
            weight = 1.0 / max(18.0, distance) ** 2
            weighted_sum += sample_rssi * weight
            weight_total += weight
        if weight_total == 0:
            return None
        return weighted_sum / weight_total

    def line_crosses_wall(self, x1, y1, x2, y2):
        if not self.floorplan or not self.wall_mask:
            return False
        key = (round(x1), round(y1), round(x2), round(y2))
        cached = self.wall_line_cache.get(key)
        if cached is not None:
            return cached

        left, top, _, _ = self.canvas_bounds()
        ix1 = int(round(x1 - left))
        iy1 = int(round(y1 - top))
        ix2 = int(round(x2 - left))
        iy2 = int(round(y2 - top))
        crosses = self.mask_line_crosses_wall(ix1, iy1, ix2, iy2)
        self.wall_line_cache[key] = crosses
        return crosses

    def mask_line_crosses_wall(self, x1, y1, x2, y2):
        dx = abs(x2 - x1)
        dy = -abs(y2 - y1)
        step_x = 1 if x1 < x2 else -1
        step_y = 1 if y1 < y2 else -1
        error = dx + dy
        x = x1
        y = y1

        while True:
            if self.is_wall_mask_pixel(x, y):
                return True
            if x == x2 and y == y2:
                return False
            doubled_error = 2 * error
            if doubled_error >= dy:
                error += dy
                x += step_x
            if doubled_error <= dx:
                error += dx
                y += step_y

    def ensure_wall_mask(self):
        threshold = self.wall_threshold.get()
        if not self.floorplan:
            return False
        if self.wall_mask is not None and self.wall_mask_threshold == threshold:
            return False
        width = self.floorplan.width()
        height = self.floorplan.height()
        mask = []
        for y in range(height):
            row = bytearray(width)
            for x in range(width):
                if self.photo_pixel_is_wall(x, y, threshold):
                    row[x] = 1
            mask.append(row)
        self.wall_mask = mask
        self.wall_mask_threshold = threshold
        self.wall_line_cache.clear()
        return True

    def is_wall_near(self, x, y, radius):
        left, top, _, _ = self.canvas_bounds()
        image_x = int(x - left)
        image_y = int(y - top)
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if self.is_wall_mask_pixel(image_x + dx, image_y + dy):
                    return True
        return False

    def is_wall_mask_pixel(self, image_x, image_y):
        if not self.wall_mask:
            return False
        if image_x < 0 or image_y < 0 or image_y >= len(self.wall_mask) or image_x >= len(self.wall_mask[image_y]):
            return False
        return bool(self.wall_mask[image_y][image_x])

    def photo_pixel_is_wall(self, image_x, image_y, threshold):
        try:
            color = self.floorplan.get(image_x, image_y)
        except tk.TclError:
            return False
        if isinstance(color, tuple):
            red, green, blue = color[:3]
        else:
            parts = color.split()
            if len(parts) != 3:
                return False
            red, green, blue = [int(part) for part in parts]
        darkness = (int(red) + int(green) + int(blue)) / 3
        return darkness <= threshold

    def invalidate_wall_cache(self):
        self.wall_mask = None
        self.wall_mask_threshold = None
        self.wall_line_cache.clear()

    def draw_samples(self):
        for index, sample in enumerate(self.samples, start=1):
            radius = 8
            color = rssi_color(sample.rssi)
            self.canvas.create_oval(sample.x - radius, sample.y - radius, sample.x + radius, sample.y + radius, fill=color, outline="#1f1f1f", width=2)
            self.canvas.create_text(sample.x, sample.y - 17, text=str(index), fill="#1f1f1f", font=("Segoe UI", 9, "bold"))

    def draw_ap_markers(self):
        for marker in self.ap_markers:
            size = 13
            points = [
                marker.x,
                marker.y - size,
                marker.x + size,
                marker.y,
                marker.x,
                marker.y + size,
                marker.x - size,
                marker.y,
            ]
            self.canvas.create_polygon(points, fill="#2f6fcf", outline="#17345f", width=2)
            self.canvas.create_text(marker.x, marker.y, text="AP", fill="#ffffff", font=("Segoe UI", 7, "bold"))
            self.canvas.create_text(marker.x, marker.y + 22, text=marker.name, fill="#17345f", font=("Segoe UI", 9, "bold"))

    def draw_legend(self, x, y):
        labels = [("-90", -90), ("-75", -75), ("-65", -65), ("-55", -55), ("-35", -35)]
        self.canvas.create_rectangle(x - 12, y - 12, x + 170, y + 62, fill="#fbfaf5", outline="#c9c5b8")
        self.canvas.create_text(x, y - 2, text="Weak", anchor="w", fill="#4a463d", font=("Segoe UI", 9))
        self.canvas.create_text(x + 124, y - 2, text="Strong", anchor="w", fill="#4a463d", font=("Segoe UI", 9))
        for i, (_, rssi) in enumerate(labels):
            self.canvas.create_rectangle(x + i * 32, y + 16, x + i * 32 + 32, y + 36, fill=rssi_color(rssi), outline="")
        self.canvas.create_text(x, y + 48, text="dBm", anchor="w", fill="#4a463d", font=("Segoe UI", 9))

    def add_sample(self, x, y, redraw=True, warn=True):
        if self.current.rssi_dbm is None:
            if warn:
                messagebox.showwarning("No WiFi reading", "No live WiFi signal is available yet.")
            return
        self.samples.append(
            Sample(
                x,
                y,
                self.current.rssi_dbm,
                self.current.ssid,
                self.current.signal_percent,
                bssid=self.current.bssid,
                channel=self.current.channel,
                band=self.current.band,
                radio_type=self.current.radio_type,
                authentication=self.current.authentication,
            )
        )
        if redraw:
            self.draw()

    def add_center_sample(self):
        left, top, right, bottom = self.canvas_bounds()
        self.add_sample((left + right) / 2, (top + bottom) / 2)

    def on_canvas_click(self, event):
        if self.pending_ap_name is not None:
            self.ap_markers.append(APMarker(event.x, event.y, self.pending_ap_name))
            self.pending_ap_name = None
            self.draw()
            return
        self.selected_sample = self.nearest_sample(event.x, event.y, 14)
        if self.selected_sample is not None:
            return
        if self.add_on_click.get():
            self.add_sample(event.x, event.y)

    def on_canvas_right_click(self, event):
        ap_index = self.nearest_ap_marker(event.x, event.y, 24)
        sample_index = self.nearest_sample(event.x, event.y, 24)
        if ap_index is not None:
            del self.ap_markers[ap_index]
            self.draw()
        elif sample_index is not None:
            del self.samples[sample_index]
            self.draw()

    def on_mouse_move(self, event):
        self.last_mouse = (event.x, event.y)
        self.coords.set(f"x: {event.x}, y: {event.y}")

    def map_center(self):
        left, top, right, bottom = self.canvas_bounds()
        return (left + right) / 2, (top + bottom) / 2

    def nearest_sample(self, x, y, max_distance):
        nearest = None
        best = max_distance
        for index, sample in enumerate(self.samples):
            distance = math.hypot(sample.x - x, sample.y - y)
            if distance <= best:
                nearest = index
                best = distance
        return nearest

    def nearest_ap_marker(self, x, y, max_distance):
        nearest = None
        best = max_distance
        for index, marker in enumerate(self.ap_markers):
            distance = math.hypot(marker.x - x, marker.y - y)
            if distance <= best:
                nearest = index
                best = distance
        return nearest

    def begin_add_ap_marker(self):
        default = f"AP {len(self.ap_markers) + 1}"
        name = simpledialog.askstring("Add AP marker", "AP label:", initialvalue=default)
        if name is None:
            return
        self.pending_ap_name = name.strip() or default
        messagebox.showinfo("Add AP marker", "Click the floor plan where this AP should appear.")

    def clear_ap_markers(self):
        if self.ap_markers and messagebox.askyesno("Clear AP markers", "Remove all AP markers?"):
            self.ap_markers.clear()
            self.draw()

    def undo_sample(self):
        if self.samples:
            self.samples.pop()
            self.draw()

    def clear_samples(self):
        if self.samples and messagebox.askyesno("Clear samples", "Remove all recorded samples?"):
            self.samples.clear()
            self.draw()

    def save_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Save WiFi survey",
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "x",
                    "y",
                    "rssi_dbm",
                    "signal_percent",
                    "ssid",
                    "bssid",
                    "band",
                    "channel",
                    "radio_type",
                    "authentication",
                    "created_at",
                ]
            )
            for sample in self.samples:
                writer.writerow(
                    [
                        sample.x,
                        sample.y,
                        sample.rssi,
                        sample.signal_percent,
                        sample.ssid,
                        sample.bssid,
                        sample.band,
                        sample.channel,
                        sample.radio_type,
                        sample.authentication,
                        sample.created_at,
                    ]
                )

    def load_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv"), ("All files", "*.*")], title="Load WiFi survey")
        if not path:
            return
        loaded = []
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                loaded.append(
                    Sample(
                        row["x"],
                        row["y"],
                        row["rssi_dbm"],
                        row.get("ssid", ""),
                        row.get("signal_percent", ""),
                        row.get("created_at") or None,
                        row.get("bssid", ""),
                        row.get("channel", ""),
                        row.get("band", ""),
                        row.get("radio_type", ""),
                        row.get("authentication", ""),
                    )
                )
        self.samples = loaded
        self.draw()

    def save_session(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("Survey session", "*.json"), ("All files", "*.*")],
            title="Save survey session",
        )
        if not path:
            return
        data = {
            "floorplan_path": self.floorplan_path,
            "settings": {
                "show_grid": self.show_grid.get(),
                "respect_walls": self.respect_walls.get(),
                "cell_size": self.cell_size.get(),
                "max_radius": self.max_radius.get(),
                "wall_threshold": self.wall_threshold.get(),
                "auto_interval": self.auto_interval.get(),
            },
            "samples": [self.sample_to_dict(sample) for sample in self.samples],
            "ap_markers": [{"x": marker.x, "y": marker.y, "name": marker.name} for marker in self.ap_markers],
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

    def load_session(self):
        path = filedialog.askopenfilename(
            filetypes=[("Survey session", "*.json"), ("All files", "*.*")],
            title="Load survey session",
        )
        if not path:
            return
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)

        settings = data.get("settings", {})
        self.show_grid.set(bool(settings.get("show_grid", self.show_grid.get())))
        self.respect_walls.set(bool(settings.get("respect_walls", self.respect_walls.get())))
        self.cell_size.set(int(settings.get("cell_size", self.cell_size.get())))
        self.max_radius.set(int(settings.get("max_radius", self.max_radius.get())))
        self.wall_threshold.set(int(settings.get("wall_threshold", self.wall_threshold.get())))
        self.auto_interval.set(int(settings.get("auto_interval", self.auto_interval.get())))

        self.samples = [self.sample_from_dict(item) for item in data.get("samples", [])]
        self.ap_markers = [APMarker(item.get("x", 0), item.get("y", 0), item.get("name", "AP")) for item in data.get("ap_markers", [])]

        floorplan_path = data.get("floorplan_path")
        self.floorplan = None
        self.floorplan_path = None
        if floorplan_path:
            try:
                self.floorplan = tk.PhotoImage(file=floorplan_path)
                self.floorplan_path = floorplan_path
            except tk.TclError:
                messagebox.showwarning("Floor plan not loaded", "The saved floor plan path could not be opened.")
        self.invalidate_wall_cache()
        self.draw()

    def sample_to_dict(self, sample):
        return {
            "x": sample.x,
            "y": sample.y,
            "rssi_dbm": sample.rssi,
            "signal_percent": sample.signal_percent,
            "ssid": sample.ssid,
            "bssid": sample.bssid,
            "band": sample.band,
            "channel": sample.channel,
            "radio_type": sample.radio_type,
            "authentication": sample.authentication,
            "created_at": sample.created_at,
        }

    def sample_from_dict(self, item):
        return Sample(
            item.get("x", 0),
            item.get("y", 0),
            item.get("rssi_dbm", -100),
            item.get("ssid", ""),
            item.get("signal_percent", ""),
            item.get("created_at") or None,
            item.get("bssid", ""),
            item.get("channel", ""),
            item.get("band", ""),
            item.get("radio_type", ""),
            item.get("authentication", ""),
        )

    def export_image(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".ppm",
            filetypes=[("Portable pixmap image", "*.ppm"), ("All files", "*.*")],
            title="Export heatmap image",
        )
        if not path:
            return
        self.write_ppm_export(path)
        messagebox.showinfo("Export image", "Image exported as a PPM file.")

    def write_ppm_export(self, path):
        left, top, right, bottom = self.canvas_bounds()
        width = int(right - left)
        height = int(bottom - top)
        pixels = [[(251, 250, 245) for _ in range(width)] for _ in range(height)]

        if self.floorplan:
            floor_w = min(width, self.floorplan.width())
            floor_h = min(height, self.floorplan.height())
            for y in range(floor_h):
                for x in range(floor_w):
                    pixels[y][x] = self.photo_pixel_tuple(x, y)

        if self.show_grid.get():
            self.paint_export_grid(pixels, width, height)

        self.paint_export_heatmap(pixels, left, top, width, height)
        self.paint_export_samples(pixels, left, top, width, height)
        self.paint_export_ap_markers(pixels, left, top, width, height)

        with open(path, "wb") as handle:
            handle.write(f"P6\n{width} {height}\n255\n".encode("ascii"))
            for row in pixels:
                for red, green, blue in row:
                    handle.write(bytes((red, green, blue)))

    def photo_pixel_tuple(self, image_x, image_y):
        try:
            color = self.floorplan.get(image_x, image_y)
        except tk.TclError:
            return 251, 250, 245
        if isinstance(color, tuple):
            return tuple(int(part) for part in color[:3])
        parts = color.split()
        if len(parts) == 3:
            return tuple(int(part) for part in parts)
        return 251, 250, 245

    def paint_export_grid(self, pixels, width, height):
        grid_color = (230, 225, 212)
        for x in range(0, width, 50):
            for y in range(height):
                pixels[y][x] = grid_color
        for y in range(0, height, 50):
            pixels[y] = [grid_color for _ in range(width)]

    def paint_export_heatmap(self, pixels, left, top, width, height):
        if not self.samples:
            return
        step = self.cell_size.get()
        radius = self.max_radius.get()
        radius_squared = radius * radius
        samples = [(sample.x, sample.y, sample.rssi) for sample in self.samples]
        use_walls = self.respect_walls.get() and self.floorplan is not None
        if use_walls:
            self.ensure_wall_mask()

        for px in range(0, width, step):
            for py in range(0, height, step):
                center_x = left + px + step / 2
                center_y = top + py + step / 2
                if use_walls and self.is_wall_near(center_x, center_y, max(1, step // 6)):
                    continue
                rssi = self.estimate_rssi(center_x, center_y, radius_squared, samples, use_walls)
                if rssi is None:
                    continue
                color = color_to_tuple(rssi_color(rssi))
                for y in range(py, min(py + step, height)):
                    for x in range(px, min(px + step, width)):
                        pixels[y][x] = self.blend_color(pixels[y][x], color, 0.55)

    def paint_export_samples(self, pixels, left, top, width, height):
        for sample in self.samples:
            color = color_to_tuple(rssi_color(sample.rssi))
            self.paint_circle(pixels, int(sample.x - left), int(sample.y - top), 8, color, width, height)
            self.paint_circle_outline(pixels, int(sample.x - left), int(sample.y - top), 8, (31, 31, 31), width, height)

    def paint_export_ap_markers(self, pixels, left, top, width, height):
        for marker in self.ap_markers:
            cx = int(marker.x - left)
            cy = int(marker.y - top)
            size = 13
            for y in range(cy - size, cy + size + 1):
                for x in range(cx - size, cx + size + 1):
                    if 0 <= x < width and 0 <= y < height and abs(x - cx) + abs(y - cy) <= size:
                        pixels[y][x] = (47, 111, 207)
            self.paint_circle(pixels, cx, cy, 3, (255, 255, 255), width, height)

    def paint_circle(self, pixels, cx, cy, radius, color, width, height):
        radius_squared = radius * radius
        for y in range(cy - radius, cy + radius + 1):
            if y < 0 or y >= height:
                continue
            for x in range(cx - radius, cx + radius + 1):
                if x < 0 or x >= width:
                    continue
                if (x - cx) ** 2 + (y - cy) ** 2 <= radius_squared:
                    pixels[y][x] = color

    def paint_circle_outline(self, pixels, cx, cy, radius, color, width, height):
        outer = radius * radius
        inner = (radius - 2) * (radius - 2)
        for y in range(cy - radius, cy + radius + 1):
            if y < 0 or y >= height:
                continue
            for x in range(cx - radius, cx + radius + 1):
                if x < 0 or x >= width:
                    continue
                distance = (x - cx) ** 2 + (y - cy) ** 2
                if inner <= distance <= outer:
                    pixels[y][x] = color

    def blend_color(self, base, overlay, alpha):
        return tuple(round(base_part * (1 - alpha) + overlay_part * alpha) for base_part, overlay_part in zip(base, overlay))

    def load_floorplan(self):
        path = filedialog.askopenfilename(
            filetypes=[("Image files", "*.png *.gif *.ppm *.pgm"), ("All files", "*.*")],
            title="Load floor plan image",
        )
        if not path:
            return
        try:
            image = tk.PhotoImage(file=path)
        except tk.TclError as exc:
            messagebox.showerror("Unsupported image", f"Could not load this image:\n{exc}")
            return
        self.floorplan = image
        self.floorplan_path = path
        self.invalidate_wall_cache()
        self.draw()

    def clear_floorplan(self):
        self.floorplan = None
        self.floorplan_path = None
        self.invalidate_wall_cache()
        self.draw()


def main():
    root = tk.Tk()
    app = HeatmapApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
