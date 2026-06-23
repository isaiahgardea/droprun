# Droprun

**P2P file sharing and messaging over Tailscale — no cloud, no limits, no middleman.**

Files travel directly between computers on your private Tailscale network. Drop files, chat, preview images, and download anything — all from a clean desktop app.

---

## Download

👉 **[Download the latest Droprun.exe from Releases](../../releases/latest)**

No install required. Just download and run.

> **Windows SmartScreen warning:** Click "More info" → "Run anyway". The app is unsigned but safe.

---

## Requirements

- Windows 10 or 11
- [Tailscale](https://tailscale.com/download) installed and connected

---

## Features

- 📁 Share files instantly — drag & drop to upload, peers download directly from you
- 📤 Send files to a peer — drag files onto their name in the sidebar
- 💬 Direct messaging — chat with any peer on your network
- 🔒 Private — only devices on your Tailscale network can connect
- 📦 Download all as ZIP — grab everything from a peer in one click
- 🖼️ Preview images and PDFs without downloading
- 🔔 Desktop notifications and message sounds
- 🎨 Six color themes
- 📋 Transfer history log
- ⚡ Ping peers to check connection speed

---

## Getting Started

1. Install [Tailscale](https://tailscale.com/download) and sign in
2. Download and run `Droprun.exe`
3. Your Tailscale IP appears in the bottom-left of the sidebar — share it with anyone who wants to connect to you
4. Other users running Droprun appear automatically in the sidebar

A full setup guide is built into the app — open Settings and click **Help Guide**.

---

## Building from Source

```bash
pip install pywebview pyinstaller
build_exe.bat
```

Output: `dist\Droprun.exe`

---

## License

MIT
