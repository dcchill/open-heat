import functools
import http.server
import json
import mimetypes
import pathlib
import socketserver
import subprocess
import urllib.parse

from wifi_heatmap import collect_network_diagnostics, measure_internet, read_wifi


PORT = 8765
ROOT = pathlib.Path(__file__).resolve().parent
WEB_ROOT = ROOT / "webui"


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class WebUiHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/wifi":
            self.send_json(wifi_reading_to_dict(read_wifi()))
            return
        self.serve_static(path)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path not in ("/api/internet", "/api/diagnostics"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if path == "/api/diagnostics":
                self.send_json(collect_network_diagnostics(
                    str(data.get("ping_host", "1.1.1.1")).strip(),
                    str(data.get("dns_host", "cloudflare.com")).strip(),
                ))
                return
            ping_ms, download_mbps = measure_internet(
                str(data.get("ping_host", "")).strip(),
                str(data.get("download_url", "")).strip(),
                max(1, int(data.get("download_bytes", 1_000_000))),
            )
            self.send_json({
                "ping_ms": ping_ms,
                "download_mbps": download_mbps,
                "speed_tested_at": current_timestamp(),
                "speed_error": "",
            })
        except (OSError, RuntimeError, ValueError, TimeoutError, subprocess.SubprocessError) as exc:
            if path == "/api/diagnostics":
                self.send_json({
                    "created_at": current_timestamp(),
                    "checks": [{"name": "Diagnostics", "ok": False, "detail": str(exc)}],
                    "ip_adapters": [],
                    "nearby_networks": [],
                })
            else:
                self.send_json({
                    "ping_ms": None,
                    "download_mbps": None,
                    "speed_tested_at": current_timestamp(),
                    "speed_error": str(exc),
                })

    def serve_static(self, path):
        relative = path.strip("/") or "index.html"
        target = (WEB_ROOT / relative).resolve()
        try:
            target.relative_to(WEB_ROOT.resolve())
        except ValueError:
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return

        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, data):
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def wifi_reading_to_dict(reading):
    return {
        "ssid": reading.ssid,
        "bssid": reading.bssid,
        "signal_percent": reading.signal_percent,
        "rssi_dbm": reading.rssi_dbm,
        "adapter": reading.adapter,
        "state": reading.state,
        "radio_type": reading.radio_type,
        "authentication": reading.authentication,
        "cipher": reading.cipher,
        "channel": reading.channel,
        "band": reading.band,
        "receive_rate": reading.receive_rate,
        "transmit_rate": reading.transmit_rate,
        "profile": reading.profile,
        "created_at": current_timestamp(),
    }


def current_timestamp():
    from time import strftime

    return strftime("%Y-%m-%d %H:%M:%S")


def main():
    if not WEB_ROOT.is_dir():
        raise SystemExit("webui folder not found")
    handler = functools.partial(WebUiHandler)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    print(f"Open Heat web UI running at http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
