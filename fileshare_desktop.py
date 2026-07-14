#!/usr/bin/env python3
"""
Droprun -- native P2P file sharing + messaging over Tailscale.
Bundle with: build_exe.bat
"""

import http.server, os, sys, json, socket, urllib.parse, mimetypes
import threading, subprocess, time, zipfile, io
from pathlib import Path
from datetime import datetime

# ── Config ───────────────────────────────────────────────────────────────────
PORT      = 8765
PIN       = ""
APP_NAME  = "Droprun"
WIN_W, WIN_H = 1080, 720
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# ── Paths ─────────────────────────────────────────────────────────────────────
def get_resource(rel):
    base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).parent
    return base / rel

SETTINGS_PATH = Path.home() / ".droprun" / "settings.json"

# ── Settings ──────────────────────────────────────────────────────────────────
_settings = {}
SHARE_DIR = Path.home() / "FileShare"

def load_settings():
    global _settings, SHARE_DIR
    try:
        if SETTINGS_PATH.exists():
            _settings = json.loads(SETTINGS_PATH.read_text("utf-8"))
            if _settings.get("download_dir"):
                SHARE_DIR = Path(_settings["download_dir"])
    except Exception:
        pass

def save_settings(data):
    global _settings, SHARE_DIR
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _settings.update(data)           # merge — never wipe keys like onboarded
    if _settings.get("download_dir"):
        SHARE_DIR = Path(_settings["download_dir"])
        SHARE_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(_settings, indent=2), "utf-8")

# ── Messages ──────────────────────────────────────────────────────────────────
_messages  = {}
_msg_lock  = threading.Lock()

def _add_message(peer_ip, direction, text, name=""):
    ts = datetime.now().strftime("%H:%M")
    with _msg_lock:
        if peer_ip not in _messages:
            _messages[peer_ip] = []
        _messages[peer_ip].append({"from": direction, "text": text, "time": ts, "name": name})

def _get_messages(peer_ip):
    with _msg_lock:
        return list(_messages.get(peer_ip, []))

# ── Transfer history ──────────────────────────────────────────────────────────
_transfers     = []
_transfer_lock = threading.Lock()

def _log_transfer(direction, fname, size_bytes, peer_ip=""):
    with _transfer_lock:
        _transfers.insert(0, {
            "direction": direction,
            "name":      fname,
            "size":      format_size(size_bytes),
            "bytes":     size_bytes,
            "peer":      peer_ip,
            "time":      datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        if len(_transfers) > 200:
            _transfers.pop()

# ── Windows notifications ─────────────────────────────────────────────────────
def notify(title, body):
    if sys.platform != "win32":
        return
    try:
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$n=[System.Windows.Forms.NotifyIcon]::new();"
            "$n.Icon=[System.Drawing.SystemIcons]::Information;"
            "$n.Visible=$true;"
            "$n.BalloonTipTitle='" + title.replace("'", "") + "';"
            "$n.BalloonTipText='" + body.replace("'", "").replace('"', '') + "';"
            "$n.ShowBalloonTip(4000);"
            "Start-Sleep 5;"
            "$n.Dispose()"
        )
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps],
            creationflags=NO_WINDOW,
        )
    except Exception:
        pass

# ── Tailscale helpers ─────────────────────────────────────────────────────────
def _ts_cmd(args):
    for exe in ["tailscale",
                r"C:\Program Files\Tailscale\tailscale.exe",
                r"C:\Program Files (x86)\Tailscale\tailscale.exe"]:
        try:
            r = subprocess.run([exe] + args, capture_output=True, text=True,
                               timeout=5, creationflags=NO_WINDOW)
            if r.returncode == 0:
                return r.stdout
        except Exception:
            pass
    return None

def get_tailscale_ip():
    out = _ts_cmd(["ip", "-4"])
    if out and out.strip():
        return out.strip()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            parts = ip.split(".")
            if len(parts) == 4 and parts[0] == "100" and 64 <= int(parts[1]) <= 127:
                return ip
    except Exception:
        pass
    return None

def get_tailscale_peers():
    out = _ts_cmd(["status", "--json"])
    if not out:
        return []
    try:
        data = json.loads(out)
        peers = []
        for peer in data.get("Peer", {}).values():
            ips  = peer.get("TailscaleIPs", [])
            ipv4 = next((ip for ip in ips if ":" not in ip), None)
            if not ipv4:
                continue
            name = peer.get("HostName") or peer.get("DNSName") or ipv4
            name = name.rstrip(".")
            peers.append({"name": name, "ip": ipv4, "online": peer.get("Online", False)})
        return peers
    except Exception:
        return []

def open_tailscale_app():
    for p in [r"C:\Program Files\Tailscale\tailscale-ipn.exe",
              r"C:\Program Files (x86)\Tailscale\tailscale-ipn.exe"]:
        if os.path.exists(p):
            subprocess.Popen([p], creationflags=NO_WINDOW)
            return True
    try:
        import webbrowser
        webbrowser.open("https://login.tailscale.com/admin/machines")
    except Exception:
        pass
    return False

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close(); return ip
    except Exception:
        return None

def get_all_ips():
    ips = {}
    ts = get_tailscale_ip()
    if ts: ips["Tailscale"] = ts
    local = get_local_ip()
    if local and not local.startswith("127."): ips["Local"] = local
    ips["Localhost"] = "127.0.0.1"
    return ips

# ── File helpers ──────────────────────────────────────────────────────────────
def format_size(n):
    for u in ["B", "KB", "MB", "GB"]:
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"

def list_files():
    try:
        return [{"name":     p.name,
                 "size":     format_size(p.stat().st_size),
                 "bytes":    p.stat().st_size,
                 "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}
                for p in sorted(SHARE_DIR.iterdir()) if p.is_file()]
    except Exception:
        return []

def parse_multipart(ct_header, body):
    boundary = None
    for part in ct_header.split(";"):
        part = part.strip()
        if part.lower().startswith("boundary="):
            boundary = part[9:].strip('"').strip("'"); break
    if not boundary: return []
    results = []
    for part in body.split(("--" + boundary).encode())[1:]:
        if part.strip() in (b"", b"--", b"--\r\n", b"--\n"): continue
        sep = b"\r\n\r\n" if b"\r\n\r\n" in part else b"\n\n"
        if sep not in part: continue
        hdr, content = part.split(sep, 1)
        if content.endswith(b"\r\n"): content = content[:-2]
        elif content.endswith(b"\n"): content = content[:-1]
        fname = None
        for line in hdr.decode("utf-8", errors="replace").splitlines():
            if "content-disposition" in line.lower() and "filename=" in line.lower():
                for tok in line.split(";"):
                    tok = tok.strip()
                    if tok.lower().startswith("filename="):
                        fname = tok[9:].strip('"').strip("'"); break
        if fname: results.append((fname, content))
    return results

def _pick_folder_dialog():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
        folder = filedialog.askdirectory(title="Choose download folder")
        root.destroy()
        return folder or ""
    except Exception:
        return ""

# ── HTTP Handler ──────────────────────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def _auth(self):
        return (not PIN) or self.headers.get("X-Pin", "") == PIN

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Pin, X-From-IP")

    def _json(self, d, s=200):
        b = json.dumps(d).encode()
        self.send_response(s)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(b)))
        self._cors()
        self.end_headers(); self.wfile.write(b)

    def _html(self, b, s=200):
        self.send_response(s)
        self.send_header("Content-Type",   "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def _serve_file(self, fpath, disposition="attachment"):
        if not fpath.exists() or not fpath.is_file():
            self._json({"error": "Not found"}, 404); return
        mime, _ = mimetypes.guess_type(str(fpath))
        mime   = mime or "application/octet-stream"
        size   = fpath.stat().st_size
        enc    = urllib.parse.quote(fpath.name)
        rng    = self.headers.get("Range")
        if rng:
            try:
                parts = rng.replace("bytes=", "").split("-")
                start = int(parts[0]) if parts[0] else 0
                end   = int(parts[1]) if len(parts) > 1 and parts[1] else size - 1
                end   = min(end, size - 1)
                length = end - start + 1
                with open(fpath, "rb") as f:
                    f.seek(start); data = f.read(length)
                self.send_response(206)
                self.send_header("Content-Type",   mime)
                self.send_header("Accept-Ranges",  "bytes")
                self.send_header("Content-Range",  f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(length))
                self._cors()
                self.end_headers(); self.wfile.write(data)
            except Exception:
                self._json({"error": "Bad range"}, 416)
        else:
            self.send_response(200)
            self.send_header("Content-Type",        mime)
            self.send_header("Accept-Ranges",       "bytes")
            self.send_header("Content-Length",      str(size))
            self.send_header("Content-Disposition",
                f'{disposition}; filename="{fpath.name}"; filename*=UTF-8\'\'{enc}')
            self._cors()
            self.end_headers()
            with open(fpath, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk: break
                    self.wfile.write(chunk)

    def do_GET(self):
        p  = urllib.parse.urlparse(self.path).path
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        if p == "/":
            tmpl = get_resource("droprun_ui.html")
            html = tmpl.read_text("utf-8").replace("__PIN_REQUIRED__",
                                                    "true" if PIN else "false")
            self._html(html.encode("utf-8"))

        elif p.startswith("/assets/"):
            fname = Path(urllib.parse.unquote(p[len("/assets/"):])).name
            self._serve_file(get_resource("Assets") / fname, disposition="inline")

        elif p == "/api/info":
            self._json({"ips": get_all_ips(), "port": PORT,
                        "hostname": socket.gethostname()})

        elif p == "/api/peers":
            self._json(get_tailscale_peers())

        elif p == "/api/files":
            self._json(list_files())

        elif p == "/api/probe":
            ip = qs.get("ip", [""])[0].strip()
            if not ip:
                self._json({"error": "no ip"}, 400)
            else:
                self._json(probe_peer(ip))

        elif p == "/api/messages":
            peer = qs.get("peer", [None])[0]
            self._json(_get_messages(peer) if peer else [])

        elif p == "/api/settings":
            self._json({"download_dir":  str(SHARE_DIR) if _settings.get("download_dir") else "",
                        "theme":         _settings.get("theme", "dark"),
                        "sound":         _settings.get("sound", True),
                        "sound_enabled": _settings.get("sound_enabled", True),
                        "notif_enabled": _settings.get("notif_enabled", False),
                        "onboarded":     _settings.get("onboarded", False)})

        elif p == "/api/ping":
            self._json({"pong": True, "ts": time.time(),
                        "hostname": socket.gethostname()})

        elif p == "/api/transfers":
            with _transfer_lock:
                self._json(list(_transfers))

        elif p == "/api/download-zip":
            if not self._auth(): self._json({"error": "Unauthorized"}, 401); return
            names_param = qs.get("files", [""])[0]
            names = ([Path(n.strip()).name for n in names_param.split(",") if n.strip()]
                     if names_param else [f["name"] for f in list_files()])
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for name in names:
                    fp = SHARE_DIR / name
                    if fp.exists() and fp.is_file():
                        zf.write(fp, name)
            data = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type",        "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="droprun_files.zip"')
            self.send_header("Content-Length",      str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        elif p.startswith("/files/"):
            if not self._auth(): self._json({"error": "Unauthorized"}, 401); return
            fname = Path(urllib.parse.unquote(p[len("/files/"):])).name
            self._serve_file(SHARE_DIR / fname)

        else:
            self._html(b"<h1>Not found</h1>", 404)

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            body   = self.rfile.read(length)
        except Exception:
            body = b""

        if p == "/api/auth":
            try: payload = json.loads(body)
            except Exception: self._json({"ok": False}); return
            self._json({"ok": (not PIN) or payload.get("pin", "") == PIN})

        elif p == "/api/upload":
            if not self._auth(): self._json({"error": "Unauthorized"}, 401); return
            from_ip = self.headers.get("X-From-IP", "") or self.client_address[0]
            files   = parse_multipart(self.headers.get("Content-Type", ""), body)
            if not files: self._json({"error": "No file"}, 400); return
            SHARE_DIR.mkdir(parents=True, exist_ok=True)
            saved = []
            for fname, data in files:
                safe = Path(fname).name
                if safe:
                    (SHARE_DIR / safe).write_bytes(data)
                    saved.append(safe)
                    _log_transfer("received", safe, len(data), from_ip)
            if saved:
                threading.Thread(
                    target=notify,
                    args=("Droprun", "Received: " + ", ".join(saved) + (" from " + from_ip if from_ip else "")),
                    daemon=True,
                ).start()
            self._json({"ok": True, "saved": saved})

        elif p == "/api/fetch-from-peer":
            if not self._auth(): self._json({"error": "Unauthorized"}, 401); return
            try:
                payload  = json.loads(body)
                peer_ip  = payload.get("ip", "").strip()
                filename = Path(payload.get("filename", "")).name
                if not peer_ip or not filename:
                    self._json({"error": "Missing ip or filename"}, 400); return
                import urllib.request as _ur
                url  = f"http://{peer_ip}:{PORT}/files/{urllib.parse.quote(filename)}"
                SHARE_DIR.mkdir(parents=True, exist_ok=True)
                dest = SHARE_DIR / filename
                _ur.urlretrieve(url, str(dest))
                size = dest.stat().st_size
                _log_transfer("downloaded", filename, size, peer_ip)
                threading.Thread(target=notify,
                    args=("Droprun", f"Downloaded: {filename}"), daemon=True).start()
                self._json({"ok": True, "saved": filename})
            except Exception as e:
                import traceback; traceback.print_exc()
                self._json({"error": str(e)}, 500)

        elif p == "/api/delete":
            if not self._auth(): self._json({"error": "Unauthorized"}, 401); return
            try: payload = json.loads(body)
            except Exception: self._json({"ok": False}); return
            fname = Path(payload.get("name", "")).name
            fpath = SHARE_DIR / fname
            if not fpath.exists(): self._json({"ok": False, "error": "Not found"}, 404); return
            fpath.unlink(); self._json({"ok": True})

        elif p == "/api/open-tailscale":
            try:
                open_tailscale_app()
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})

        elif p == "/api/open-folder":
            try:
                SHARE_DIR.mkdir(parents=True, exist_ok=True)
                os.startfile(str(SHARE_DIR))
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})

        elif p == "/api/pick-files":
            # Browser-only fallback (desktop app uses the pywebview JS API).
            # PowerShell dialog is safe from a worker thread; tkinter is not.
            try:
                import shutil as _sh2
                SHARE_DIR.mkdir(parents=True, exist_ok=True)
                ps = (
                    "Add-Type -AssemblyName System.Windows.Forms;"
                    "$owner=New-Object System.Windows.Forms.Form;"
                    "$owner.TopMost=$true;"
                    "$d=New-Object System.Windows.Forms.OpenFileDialog;"
                    "$d.Multiselect=$true;$d.Title='Select files to share';"
                    "if($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK)"
                    "{$d.FileNames -join \"`n\"}"
                )
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                    capture_output=True, text=True, creationflags=NO_WINDOW,
                )
                file_paths = [x.strip() for x in r.stdout.strip().splitlines() if x.strip()] if r.stdout else []
                if not file_paths:
                    self._json({"ok": False, "cancelled": True}); return
                saved, errors = [], []
                for src_path in file_paths:
                    try:
                        src = Path(src_path); dest = SHARE_DIR / src.name
                        if src.resolve() != dest.resolve():
                            _sh2.copy2(str(src), str(dest))
                            _log_transfer("received", src.name, src.stat().st_size, "local")
                        saved.append(src.name)
                    except Exception as copy_e:
                        errors.append({"name": Path(src_path).name, "error": str(copy_e)})
                self._json({"ok": True, "saved": saved, "errors": errors})
            except Exception as e:
                self._json({"error": str(e)}, 500)

        elif p == "/api/settings":
            try: data = json.loads(body)
            except Exception: self._json({"ok": False}); return
            save_settings(data); self._json({"ok": True})

        elif p == "/api/pick-folder":
            folder = _pick_folder_dialog()
            self._json({"folder": folder})

        elif p == "/api/send-message":
            try: payload = json.loads(body)
            except Exception: self._json({"ok": False}); return
            to_ip = payload.get("to",   "")
            text  = payload.get("text", "").strip()
            if not to_ip or not text: self._json({"ok": False}); return
            _add_message(to_ip, "me", text)
            import urllib.request
            try:
                fwd = json.dumps({
                    "from": get_tailscale_ip() or "unknown",
                    "text": text,
                    "name": socket.gethostname(),
                }).encode()
                req = urllib.request.Request(
                    f"http://{to_ip}:{PORT}/api/receive-message",
                    data=fwd, headers={"Content-Type": "application/json"}, method="POST",
                )
                urllib.request.urlopen(req, timeout=5)
                self._json({"ok": True})
            except Exception:
                self._json({"ok": True, "warning": "Peer may be offline"})

        elif p == "/api/receive-message":
            try: payload = json.loads(body)
            except Exception: self._json({"ok": False}); return
            from_ip = payload.get("from", "unknown")
            text    = payload.get("text", "").strip()
            name    = payload.get("name", from_ip)
            if text:
                _add_message(from_ip, "them", text, name)
            self._json({"ok": True})

        elif p == "/api/log-transfer":
            try: payload = json.loads(body)
            except Exception: self._json({"ok": False}); return
            _log_transfer(
                payload.get("direction", "sent"),
                payload.get("name",      ""),
                payload.get("bytes",     0),
                payload.get("peer",      ""),
            )
            self._json({"ok": True})

        else:
            self._json({"error": "Not found"}, 404)

# ── Connectivity / firewall helpers ─────────────────────────────────────────────
def probe_peer(ip):
    """Diagnose why a peer can't be reached.
    device_online = host answers ICMP ping (reachable on the tailnet)
    port_open     = the Droprun app is listening on PORT (TCP connect succeeds)"""
    port_open = False
    try:
        with socket.create_connection((ip, PORT), timeout=2):
            port_open = True
    except Exception:
        port_open = False
    device_online = False
    try:
        if sys.platform == "win32":
            cmd = ["ping", "-n", "1", "-w", "1500", ip]
        else:
            cmd = ["ping", "-c", "1", "-W", "2", ip]
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
        device_online = (r.returncode == 0)
    except Exception:
        device_online = False
    return {"ip": ip, "device_online": device_online, "port_open": port_open}


def ensure_firewall_rule():
    """Best-effort Windows Firewall inbound allow rule for the app port so peers
    can reach us. Succeeds when the app is run elevated; otherwise fails quietly
    (Windows may still prompt to allow the app on first bind). Idempotent."""
    if sys.platform != "win32":
        return
    rule_name = f"Droprun (TCP {PORT})"
    try:
        chk = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={rule_name}"],
            capture_output=True, text=True, creationflags=NO_WINDOW,
        )
        if chk.returncode == 0:
            return  # rule already exists
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "add", "rule",
             f"name={rule_name}", "dir=in", "action=allow",
             "protocol=TCP", f"localport={PORT}"],
            capture_output=True, text=True, creationflags=NO_WINDOW,
        )
    except Exception:
        pass


# ── Server ────────────────────────────────────────────────────────────────────
def run_server():
    with http.server.ThreadingHTTPServer(("", PORT), Handler) as srv:
        srv.serve_forever()

# ── JS API ────────────────────────────────────────────────────────────────────
_webview_window = None   # set in main() so JsApi can call dialogs

class JsApi:
    def open_folder_dialog(self):
        global _webview_window
        try:
            import webview as _wv
            result = _webview_window.create_file_dialog(_wv.FOLDER_DIALOG)
            return result[0] if result else ""
        except Exception:
            # Fallback: PowerShell folder picker (no tkinter needed)
            try:
                ps = (
                    "[void][System.Reflection.Assembly]::LoadWithPartialName('System.windows.forms');"
                    "$f=New-Object System.Windows.Forms.FolderBrowserDialog;"
                    "$f.Description='Choose download folder';"
                    "[void]$f.ShowDialog();"
                    "Write-Output $f.SelectedPath"
                )
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                    capture_output=True, text=True, creationflags=NO_WINDOW
                )
                return r.stdout.strip()
            except Exception:
                return ""

    def pick_and_upload_files(self):
        """Open a native file dialog (on the pywebview main thread) and copy the
        selected files into SHARE_DIR. Uses webview's own dialog API — no tkinter
        (which crashes worker threads) — with a PowerShell fallback."""
        global _webview_window
        import traceback as _tb, datetime as _dt
        _log_path = Path.home() / ".droprun" / "debug.log"
        try:
            _log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        def _log(msg):
            try:
                with open(_log_path, "a", encoding="utf-8") as f:
                    f.write(f"[{_dt.datetime.now().isoformat()}] {msg}\n")
            except Exception:
                pass

        _log("pick_and_upload_files called")
        file_paths = []

        # 1. pywebview native dialog (correct, thread-safe on the GUI thread).
        try:
            import webview as _wv
            _log("trying webview.create_file_dialog...")
            result = _webview_window.create_file_dialog(_wv.OPEN_DIALOG, allow_multiple=True)
            _log(f"webview dialog result: {result!r}")
            if result:
                file_paths = list(result)
        except Exception as e:
            _log(f"webview dialog failed: {e}\n{_tb.format_exc()}")

        # 2. Fallback: PowerShell OpenFileDialog.
        if not file_paths:
            try:
                ps = (
                    "Add-Type -AssemblyName System.Windows.Forms;"
                    "$owner=New-Object System.Windows.Forms.Form;"
                    "$owner.TopMost=$true;"
                    "$d=New-Object System.Windows.Forms.OpenFileDialog;"
                    "$d.Multiselect=$true;$d.Title='Select files to share';"
                    "if($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK)"
                    "{$d.FileNames -join \"`n\"}"
                )
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                    capture_output=True, text=True, creationflags=NO_WINDOW,
                )
                _log(f"powershell rc={r.returncode} stdout={r.stdout!r}")
                if r.stdout and r.stdout.strip():
                    file_paths = [p.strip() for p in r.stdout.strip().splitlines() if p.strip()]
            except Exception as e:
                _log(f"powershell failed: {e}\n{_tb.format_exc()}")

        _log(f"file_paths resolved: {file_paths!r}")
        if not file_paths:
            return {"ok": False, "cancelled": True}

        import shutil
        SHARE_DIR.mkdir(parents=True, exist_ok=True)
        saved, errors = [], []
        for src_path in file_paths:
            try:
                src = Path(src_path)
                dest = SHARE_DIR / src.name
                if src.resolve() == dest.resolve():
                    saved.append(src.name)
                    _log(f"already in share dir: {src.name}")
                    continue
                shutil.copy2(str(src), str(dest))
                saved.append(src.name)
                _log_transfer("received", src.name, src.stat().st_size, "local")
            except Exception as e:
                errors.append({"name": Path(src_path).name, "error": str(e)})
                _log(f"copy error: {e}")
        if saved:
            threading.Thread(target=notify,
                args=("Droprun", "Added: " + ", ".join(saved)), daemon=True).start()
        _log(f"done: saved={saved} errors={errors}")
        return {"ok": True, "saved": saved, "errors": errors}

    def open_share_folder(self):
        """Open the share directory in the OS file explorer."""
        try:
            SHARE_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(SHARE_DIR))
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_help(self):
        try:
            path = get_resource("Droprun_Help_Guide.docx")
            if path.exists():
                os.startfile(str(path))
                return {"ok": True}
            return {"ok": False, "error": "Help file not found"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def save_settings_api(self, data_json):
        try:
            data = json.loads(data_json)
            save_settings(data)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_settings_api(self):
        return {
            "download_dir":  str(SHARE_DIR) if _settings.get("download_dir") else "",
            "theme":         _settings.get("theme", "dark"),
            "sound_enabled": _settings.get("sound_enabled", True),
            "notif_enabled": _settings.get("notif_enabled", False),
            "onboarded":     _settings.get("onboarded", False),
        }

    def open_tailscale(self):
        result = {}
        def _run():
            try:
                for p in [r"C:\Program Files\Tailscale\tailscale-ipn.exe",
                          r"C:\Program Files (x86)\Tailscale\tailscale-ipn.exe"]:
                    if os.path.exists(p):
                        subprocess.Popen([p], creationflags=NO_WINDOW)
                        result["ok"] = True; return
                import webbrowser
                webbrowser.open("https://login.tailscale.com/admin/machines")
                result["ok"] = True; result["fallback"] = True
            except Exception as e:
                result["ok"] = False; result["error"] = str(e)
        t = threading.Thread(target=_run, daemon=True)
        t.start(); t.join(timeout=5)
        return result

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global _webview_window
    load_settings()
    SHARE_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=ensure_firewall_rule, daemon=True).start()
    threading.Thread(target=run_server, daemon=True).start()
    time.sleep(0.5)

    icon_path = get_resource("Assets/Droprun.ico")
    icon_str  = str(icon_path) if icon_path.exists() else None

    try:
        import webview
        api = JsApi()
        _webview_window = webview.create_window(
            APP_NAME, f"http://localhost:{PORT}",
            width=WIN_W, height=WIN_H,
            resizable=True, min_size=(720, 500), js_api=api,
        )
        _wv_storage = str(Path.home() / ".droprun" / "webview")
        webview.start(debug=False, icon=icon_str, storage_path=_wv_storage)
        os._exit(0)   # window closed — kill process so port 8765 is freed
    except TypeError:
        import webview
        api = JsApi()
        _webview_window = webview.create_window(
            APP_NAME, f"http://localhost:{PORT}",
            width=WIN_W, height=WIN_H,
            resizable=True, min_size=(720, 500), js_api=api,
        )
        _wv_storage = str(Path.home() / ".droprun" / "webview")
        webview.start(debug=False, storage_path=_wv_storage)
        os._exit(0)
    except ImportError:
        import webbrowser
        webbrowser.open(f"http://localhost:{PORT}")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    main()
