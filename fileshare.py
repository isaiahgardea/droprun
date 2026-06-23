#!/usr/bin/env python3
"""
FileShare - Simple P2P file sharing over Tailscale
Run this on both machines. Each person accesses the other's files at:
  http://<their-tailscale-ip>:8765

Usage:
  python fileshare.py
  python fileshare.py --pin mysecret
  python fileshare.py --port 9000 --pin mysecret
"""

import http.server
import os
import sys
import json
import socket
import argparse
import urllib.parse
import io
import html
import mimetypes
import threading
import webbrowser
import struct
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_PORT = 8765
DEFAULT_PIN  = ""          # Set a PIN here to always require it, e.g. "hunter2"
SHARE_DIR    = Path.home() / "FileShare"
APP_NAME     = "FileShare"
# ─────────────────────────────────────────────────────────────────────────────


def get_all_ips():
    """Return a dict of interface-name -> IP, highlighting Tailscale."""
    results = {}
    try:
        hostname = socket.gethostname()
        infos = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for info in infos:
            ip = info[4][0]
            if ip.startswith("127."):
                continue
            if ip.startswith("100.") or ip.startswith("100.6") or ip.startswith("100.7") or ip.startswith("100.8") or ip.startswith("100.9") or ip.startswith("100.1"):
                results["Tailscale"] = ip
            else:
                results.setdefault("Local", ip)
    except Exception:
        pass
    # Always add localhost
    results["Localhost"] = "127.0.0.1"
    return results


def format_size(n_bytes):
    for unit in ["B", "KB", "MB", "GB"]:
        if n_bytes < 1024:
            return f"{n_bytes:.1f} {unit}"
        n_bytes /= 1024
    return f"{n_bytes:.1f} TB"


def list_files():
    files = []
    for p in sorted(SHARE_DIR.iterdir()):
        if p.is_file():
            stat = p.stat()
            files.append({
                "name": p.name,
                "size": format_size(stat.st_size),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
    return files


def parse_multipart(content_type_header, body_bytes):
    """Parse a multipart/form-data body. Returns list of (filename, data) tuples."""
    boundary = None
    for part in content_type_header.split(";"):
        part = part.strip()
        if part.lower().startswith("boundary="):
            boundary = part[9:].strip('"').strip("'")
            break
    if not boundary:
        return []

    delimiter = ("--" + boundary).encode()
    results = []
    parts = body_bytes.split(delimiter)
    for part in parts[1:]:
        if part.strip() in (b"", b"--", b"--\r\n", b"--\n"):
            continue
        # Split headers from body
        if b"\r\n\r\n" in part:
            header_block, content = part.split(b"\r\n\r\n", 1)
        elif b"\n\n" in part:
            header_block, content = part.split(b"\n\n", 1)
        else:
            continue
        # Strip trailing boundary marker
        if content.endswith(b"\r\n"):
            content = content[:-2]
        elif content.endswith(b"\n"):
            content = content[:-1]

        # Parse Content-Disposition
        filename = None
        for line in header_block.decode("utf-8", errors="replace").splitlines():
            line_lower = line.lower()
            if "content-disposition" in line_lower and "filename=" in line_lower:
                for token in line.split(";"):
                    token = token.strip()
                    if token.lower().startswith("filename="):
                        filename = token[9:].strip('"').strip("'")
                        break
        if filename:
            results.append((filename, content))
    return results


PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FileShare</title>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --border: #2a2d3a;
    --accent: #6c8ef5;
    --accent-hover: #8aa4ff;
    --text: #e2e4ef;
    --text-muted: #8b8fa8;
    --green: #4ade80;
    --red: #f87171;
    --radius: 10px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; min-height: 100vh; }

  /* ── Header ── */
  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; }
  .logo { font-size: 18px; font-weight: 700; color: var(--accent); letter-spacing: -0.3px; }
  .ip-badges { display: flex; gap: 8px; flex-wrap: wrap; }
  .badge { display: inline-flex; align-items: center; gap: 6px; background: var(--bg); border: 1px solid var(--border); border-radius: 20px; padding: 4px 12px; font-size: 12px; }
  .badge .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--text-muted); }
  .badge.tailscale .dot { background: var(--green); }
  .badge .label { color: var(--text-muted); margin-right: 2px; }

  /* ── Main layout ── */
  main { max-width: 860px; margin: 0 auto; padding: 32px 16px; }
  h2 { font-size: 14px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 14px; }

  /* ── Upload zone ── */
  .upload-zone { border: 2px dashed var(--border); border-radius: var(--radius); padding: 36px 24px; text-align: center; cursor: pointer; transition: border-color 0.15s, background 0.15s; margin-bottom: 32px; position: relative; }
  .upload-zone:hover, .upload-zone.drag-over { border-color: var(--accent); background: rgba(108,142,245,0.06); }
  .upload-icon { font-size: 36px; margin-bottom: 10px; }
  .upload-text { color: var(--text-muted); font-size: 14px; }
  .upload-text strong { color: var(--text); }
  #file-input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
  .upload-btn { display: inline-block; margin-top: 14px; background: var(--accent); color: #fff; border: none; border-radius: 6px; padding: 8px 20px; font-size: 13px; font-weight: 600; cursor: pointer; transition: background 0.15s; }
  .upload-btn:hover { background: var(--accent-hover); }

  /* ── Progress bar ── */
  #upload-status { margin-top: 10px; font-size: 13px; color: var(--text-muted); display: none; }
  #progress-bar-wrap { background: var(--border); border-radius: 4px; height: 6px; margin-top: 8px; overflow: hidden; display: none; }
  #progress-bar { height: 100%; background: var(--accent); width: 0%; transition: width 0.1s; border-radius: 4px; }

  /* ── File list ── */
  .file-list { display: flex; flex-direction: column; gap: 8px; }
  .file-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 18px; display: flex; align-items: center; gap: 14px; transition: border-color 0.15s; }
  .file-card:hover { border-color: var(--accent); }
  .file-icon { font-size: 24px; flex-shrink: 0; }
  .file-info { flex: 1; min-width: 0; }
  .file-name { font-size: 14px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .file-meta { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
  .file-actions { display: flex; gap: 8px; flex-shrink: 0; }
  .btn-dl { background: var(--accent); color: #fff; border: none; border-radius: 6px; padding: 6px 14px; font-size: 12px; font-weight: 600; cursor: pointer; text-decoration: none; transition: background 0.15s; }
  .btn-dl:hover { background: var(--accent-hover); }
  .btn-del { background: transparent; color: var(--text-muted); border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; font-size: 12px; cursor: pointer; transition: all 0.15s; }
  .btn-del:hover { border-color: var(--red); color: var(--red); }

  .empty-state { text-align: center; padding: 48px 24px; color: var(--text-muted); font-size: 14px; }
  .empty-icon { font-size: 40px; margin-bottom: 12px; }

  /* ── Toast ── */
  #toast { position: fixed; bottom: 24px; right: 24px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 18px; font-size: 13px; opacity: 0; transition: opacity 0.2s; pointer-events: none; z-index: 999; }
  #toast.show { opacity: 1; }
  #toast.error { border-color: var(--red); color: var(--red); }
  #toast.success { border-color: var(--green); color: var(--green); }

  /* ── PIN overlay ── */
  #pin-overlay { position: fixed; inset: 0; background: var(--bg); display: flex; align-items: center; justify-content: center; z-index: 100; }
  .pin-box { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 36px 40px; text-align: center; width: 320px; }
  .pin-box h2 { font-size: 20px; font-weight: 700; margin-bottom: 6px; color: var(--text); text-transform: none; letter-spacing: 0; }
  .pin-box p { color: var(--text-muted); font-size: 13px; margin-bottom: 24px; }
  .pin-box input { width: 100%; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; color: var(--text); font-size: 16px; padding: 10px 14px; outline: none; text-align: center; letter-spacing: 4px; }
  .pin-box input:focus { border-color: var(--accent); }
  .pin-box button { width: 100%; margin-top: 14px; background: var(--accent); color: #fff; border: none; border-radius: 8px; padding: 10px; font-size: 14px; font-weight: 600; cursor: pointer; }
  .pin-error { color: var(--red); font-size: 12px; margin-top: 8px; display: none; }
</style>
</head>
<body>

<div id="pin-overlay" style="display:none">
  <div class="pin-box">
    <div style="font-size:36px;margin-bottom:10px">🔒</div>
    <h2>PIN Required</h2>
    <p>Enter the PIN to access this file share.</p>
    <input type="password" id="pin-input" placeholder="••••••" autocomplete="off">
    <button onclick="submitPin()">Unlock</button>
    <div class="pin-error" id="pin-error">Incorrect PIN. Try again.</div>
  </div>
</div>

<header>
  <div class="logo">📁 FileShare</div>
  <div class="ip-badges" id="ip-badges"></div>
</header>

<main>
  <h2>Upload Files</h2>
  <div class="upload-zone" id="upload-zone">
    <input type="file" id="file-input" multiple>
    <div class="upload-icon">☁️</div>
    <div class="upload-text"><strong>Drag &amp; drop files here</strong><br>or click to browse</div>
    <div id="upload-status"></div>
    <div id="progress-bar-wrap"><div id="progress-bar"></div></div>
  </div>

  <h2>Shared Files</h2>
  <div class="file-list" id="file-list">
    <div class="empty-state"><div class="empty-icon">📂</div>No files shared yet.</div>
  </div>
</main>

<div id="toast"></div>

<script>
const PIN_REQUIRED = __PIN_REQUIRED__;

function showToast(msg, type="success") {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "show " + type;
  setTimeout(() => t.className = "", 2500);
}

// ── PIN ──────────────────────────────────────────────────────────────────────
function checkPin() {
  if (!PIN_REQUIRED) return;
  const stored = sessionStorage.getItem("fileshare_pin");
  if (!stored) {
    document.getElementById("pin-overlay").style.display = "flex";
    document.getElementById("pin-input").focus();
  }
}

function submitPin() {
  const pin = document.getElementById("pin-input").value;
  fetch("/api/auth", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({pin})
  }).then(r => r.json()).then(d => {
    if (d.ok) {
      sessionStorage.setItem("fileshare_pin", pin);
      document.getElementById("pin-overlay").style.display = "none";
      loadFiles();
    } else {
      document.getElementById("pin-error").style.display = "block";
      document.getElementById("pin-input").value = "";
      document.getElementById("pin-input").focus();
    }
  });
}
document.addEventListener("DOMContentLoaded", () => {
  if (PIN_REQUIRED) {
    document.getElementById("pin-input").addEventListener("keydown", e => {
      if (e.key === "Enter") submitPin();
    });
  }
});

// ── IP badges ────────────────────────────────────────────────────────────────
fetch("/api/info").then(r=>r.json()).then(d => {
  const wrap = document.getElementById("ip-badges");
  for (const [label, ip] of Object.entries(d.ips)) {
    const b = document.createElement("div");
    b.className = "badge" + (label === "Tailscale" ? " tailscale" : "");
    b.innerHTML = `<span class="dot"></span><span class="label">${label}</span><strong>${ip}:${d.port}</strong>`;
    wrap.appendChild(b);
  }
});

// ── File list ─────────────────────────────────────────────────────────────────
function fileIcon(name) {
  const ext = name.split(".").pop().toLowerCase();
  const map = {
    pdf:"📄", zip:"🗜️", tar:"🗜️", gz:"🗜️", "7z":"🗜️", rar:"🗜️",
    jpg:"🖼️", jpeg:"🖼️", png:"🖼️", gif:"🖼️", webp:"🖼️", svg:"🖼️", bmp:"🖼️",
    mp4:"🎬", mov:"🎬", avi:"🎬", mkv:"🎬", webm:"🎬",
    mp3:"🎵", wav:"🎵", flac:"🎵", ogg:"🎵",
    doc:"📝", docx:"📝", txt:"📝", md:"📝",
    xls:"📊", xlsx:"📊", csv:"📊",
    ppt:"📊", pptx:"📊",
    py:"🐍", js:"📜", ts:"📜", html:"🌐", css:"🎨", json:"📋",
    exe:"⚙️", msi:"⚙️",
  };
  return map[ext] || "📁";
}

function loadFiles() {
  const headers = {};
  const pin = sessionStorage.getItem("fileshare_pin");
  if (pin) headers["X-Pin"] = pin;

  fetch("/api/files", {headers}).then(r => r.json()).then(files => {
    const list = document.getElementById("file-list");
    if (!files.length) {
      list.innerHTML = '<div class="empty-state"><div class="empty-icon">📂</div>No files shared yet.<br>Drop files above to share them.</div>';
      return;
    }
    list.innerHTML = files.map(f => `
      <div class="file-card" id="card-${encodeURIComponent(f.name)}">
        <div class="file-icon">${fileIcon(f.name)}</div>
        <div class="file-info">
          <div class="file-name" title="${f.name}">${f.name}</div>
          <div class="file-meta">${f.size} &nbsp;·&nbsp; ${f.modified}</div>
        </div>
        <div class="file-actions">
          <a class="btn-dl" href="/files/${encodeURIComponent(f.name)}" download="${f.name}">⬇ Download</a>
          <button class="btn-del" onclick="deleteFile('${f.name.replace(/'/g,"\\'")}')">🗑</button>
        </div>
      </div>`).join("");
  }).catch(() => showToast("Could not load files", "error"));
}

function deleteFile(name) {
  if (!confirm(`Delete "${name}"?`)) return;
  const headers = {"Content-Type":"application/json"};
  const pin = sessionStorage.getItem("fileshare_pin");
  if (pin) headers["X-Pin"] = pin;
  fetch("/api/delete", {
    method: "POST",
    headers,
    body: JSON.stringify({name})
  }).then(r => r.json()).then(d => {
    if (d.ok) { showToast("Deleted " + name); loadFiles(); }
    else showToast(d.error || "Delete failed", "error");
  });
}

// ── Upload ────────────────────────────────────────────────────────────────────
const zone = document.getElementById("upload-zone");
const fileInput = document.getElementById("file-input");

zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("drag-over"); });
zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
zone.addEventListener("drop", e => {
  e.preventDefault();
  zone.classList.remove("drag-over");
  uploadFiles(e.dataTransfer.files);
});
fileInput.addEventListener("change", () => uploadFiles(fileInput.files));

function uploadFiles(files) {
  if (!files.length) return;
  const status = document.getElementById("upload-status");
  const barWrap = document.getElementById("progress-bar-wrap");
  const bar = document.getElementById("progress-bar");
  const pin = sessionStorage.getItem("fileshare_pin");

  let done = 0;
  const total = files.length;
  status.style.display = "block";
  barWrap.style.display = "block";
  bar.style.width = "0%";

  function uploadOne(file) {
    const fd = new FormData();
    fd.append("file", file, file.name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    if (pin) xhr.setRequestHeader("X-Pin", pin);
    xhr.upload.onprogress = e => {
      if (e.lengthComputable) {
        const pct = Math.round(((done + e.loaded / e.total) / total) * 100);
        bar.style.width = pct + "%";
      }
    };
    xhr.onload = () => {
      done++;
      bar.style.width = Math.round((done / total) * 100) + "%";
      status.textContent = `Uploaded ${done} of ${total} file(s)`;
      if (done === total) {
        setTimeout(() => {
          status.style.display = "none";
          barWrap.style.display = "none";
          status.textContent = "";
          fileInput.value = "";
          loadFiles();
        }, 1000);
        showToast(`Uploaded ${total} file(s)`);
      }
    };
    xhr.onerror = () => showToast("Upload failed for " + file.name, "error");
    xhr.send(fd);
  }

  for (const f of files) uploadOne(f);
}

// ── Init ──────────────────────────────────────────────────────────────────────
checkPin();
if (!PIN_REQUIRED) loadFiles();
</script>
</body>
</html>
"""


def make_html(pin_required: bool) -> bytes:
    return PAGE_HTML.replace("__PIN_REQUIRED__", "true" if pin_required else "false").encode()


class Handler(http.server.BaseHTTPRequestHandler):
    pin: str = ""
    port: int = DEFAULT_PORT

    def log_message(self, fmt, *args):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}] {self.address_string()} — {fmt % args}")

    # ── Auth helper ──────────────────────────────────────────────────────────
    def _auth_ok(self) -> bool:
        if not self.pin:
            return True
        return self.headers.get("X-Pin", "") == self.pin

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, body: bytes, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── GET ──────────────────────────────────────────────────────────────────
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/":
            self._send_html(make_html(bool(self.pin)))

        elif path == "/api/info":
            self._send_json({"ips": get_all_ips(), "port": self.port})

        elif path == "/api/files":
            if not self._auth_ok():
                self._send_json({"error": "Unauthorized"}, 401)
                return
            self._send_json(list_files())

        elif path.startswith("/files/"):
            if not self._auth_ok():
                self._send_json({"error": "Unauthorized"}, 401)
                return
            fname = urllib.parse.unquote(path[len("/files/"):])
            # Sanitize: no directory traversal
            fname = Path(fname).name
            fpath = SHARE_DIR / fname
            if not fpath.exists() or not fpath.is_file():
                self._send_json({"error": "Not found"}, 404)
                return
            mime, _ = mimetypes.guess_type(str(fpath))
            mime = mime or "application/octet-stream"
            data = fpath.read_bytes()
            encoded_name = urllib.parse.quote(fname)
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Disposition",
                             f'attachment; filename="{fname}"; filename*=UTF-8\'\'{encoded_name}')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        else:
            self._send_html(b"<h1>Not Found</h1>", 404)

    # ── POST ─────────────────────────────────────────────────────────────────
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if path == "/api/auth":
            try:
                payload = json.loads(body)
            except Exception:
                self._send_json({"ok": False, "error": "Bad JSON"}, 400)
                return
            ok = (not self.pin) or (payload.get("pin", "") == self.pin)
            self._send_json({"ok": ok})

        elif path == "/api/upload":
            if not self._auth_ok():
                self._send_json({"error": "Unauthorized"}, 401)
                return
            ct = self.headers.get("Content-Type", "")
            files = parse_multipart(ct, body)
            if not files:
                self._send_json({"error": "No file found in request"}, 400)
                return
            saved = []
            for fname, data in files:
                # Sanitize filename
                safe = Path(fname).name
                if not safe:
                    continue
                dest = SHARE_DIR / safe
                dest.write_bytes(data)
                saved.append(safe)
                print(f"  [upload] saved: {safe} ({format_size(len(data))})")
            self._send_json({"ok": True, "saved": saved})

        elif path == "/api/delete":
            if not self._auth_ok():
                self._send_json({"error": "Unauthorized"}, 401)
                return
            try:
                payload = json.loads(body)
            except Exception:
                self._send_json({"ok": False, "error": "Bad JSON"}, 400)
                return
            fname = Path(payload.get("name", "")).name
            fpath = SHARE_DIR / fname
            if not fpath.exists():
                self._send_json({"ok": False, "error": "File not found"}, 404)
                return
            fpath.unlink()
            print(f"  [delete] removed: {fname}")
            self._send_json({"ok": True})

        else:
            self._send_json({"error": "Not found"}, 404)


def main():
    parser = argparse.ArgumentParser(description="FileShare — simple file sharing over Tailscale")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port to listen on (default: {DEFAULT_PORT})")
    parser.add_argument("--pin",  type=str, default=DEFAULT_PIN,  help="Optional PIN to protect your files")
    args = parser.parse_args()

    # Create share directory
    SHARE_DIR.mkdir(parents=True, exist_ok=True)

    # Configure handler
    Handler.pin  = args.pin
    Handler.port = args.port

    ips = get_all_ips()
    ts_ip = ips.get("Tailscale")
    local_ip = ips.get("Local", "127.0.0.1")

    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║          📁  FileShare  is running       ║")
    print("  ╚══════════════════════════════════════════╝")
    print()
    print(f"  Share folder : {SHARE_DIR}")
    print(f"  Local access : http://localhost:{args.port}")
    if local_ip:
        print(f"  LAN access   : http://{local_ip}:{args.port}")
    if ts_ip:
        print(f"  Tailscale    : http://{ts_ip}:{args.port}  ← share this with your friend")
    else:
        print(f"  Tailscale    : (not detected — install Tailscale and connect)")
    if args.pin:
        print(f"  PIN          : set (required to access files)")
    else:
        print(f"  PIN          : none (anyone on Tailscale can access your files)")
    print()
    print("  Opening browser...")
    print("  Press Ctrl+C to stop.")
    print()

    # Open browser after a short delay
    url = f"http://localhost:{args.port}"
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    with http.server.ThreadingHTTPServer(("", args.port), Handler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n  Stopped. Goodbye!")


if __name__ == "__main__":
    main()
