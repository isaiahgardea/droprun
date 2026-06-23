# FileShare over Tailscale — Setup Guide

A private, direct file-sharing connection between you and a friend using Tailscale as the network tunnel and a lightweight Python web server as the interface. No cloud storage, no third-party accounts beyond Tailscale's free tier.

---

## How It Works

```
Your PC  ──── Tailscale VPN ────  Friend's PC
  │                                    │
fileshare.py:8765             fileshare.py:8765
  │                                    │
You visit their IP                They visit your IP
to grab their files               to grab your files
```

Both of you run the same `fileshare.py` app. You each get a stable Tailscale IP (like `100.x.x.x`) that only the two of you can reach. Drop files into your `FileShare` folder → your friend downloads them from your IP in their browser, and vice versa.

---

## Part 1 — Install Tailscale (Both of You)

### Step 1 — Create a Tailscale account
1. Go to **https://tailscale.com** and click **Get Started**
2. Sign in with Google, Microsoft, or GitHub — whichever you prefer
3. You and your friend each need your **own separate account**

### Step 2 — Install on Windows
1. Download the Windows installer from **https://tailscale.com/download/windows**
2. Run the installer and follow the prompts
3. Tailscale will appear in your system tray (bottom-right corner)
4. Click the tray icon → **Log in** → sign in with your account
5. Your machine will appear as "connected" in your Tailscale admin panel

### Step 3 — Find your Tailscale IP
- Click the Tailscale tray icon → your IP is shown at the top (format: `100.x.x.x`)
- Or go to **https://login.tailscale.com/admin/machines** to see all your devices

---

## Part 2 — Connect You and Your Friend

Tailscale keeps each account's devices in a private "tailnet." To talk to your friend's machine, you need to **share your node** with them (or they share theirs with you).

### Option A — Node Sharing (Recommended)
1. Go to **https://login.tailscale.com/admin/machines**
2. Click the **"..."** menu next to your machine
3. Click **Share** → enter your friend's Tailscale **email address**
4. They'll get an email invite — they accept it, and your machine appears in their Tailscale network list
5. Repeat: have them share their machine with your email too
6. Now you can each reach the other's Tailscale IP directly

### Option B — Same Tailnet (Simpler, less private)
- If you trust each other fully, one person can invite the other to join the same tailnet under one account
- Go to **https://login.tailscale.com/admin/users** → Invite user
- Both devices then share the same network automatically

---

## Part 3 — Run the File Share App

### Step 1 — Make sure Python is installed
Open **Command Prompt** (`Win + R` → type `cmd`) and run:
```
python --version
```
If you see `Python 3.x.x`, you're good. If not, download Python from **https://python.org/downloads** — check "Add Python to PATH" during install.

### Step 2 — Place the app files
Put these two files anywhere convenient — e.g., your Desktop or `C:\FileShare\`:
- `fileshare.py`
- `START_FILESHARE.bat`

### Step 3 — Start the server
Double-click **`START_FILESHARE.bat`** (or run `python fileshare.py` in a terminal).

A browser window will open showing your file share dashboard.

The app automatically creates a `FileShare` folder in your home directory (`C:\Users\YourName\FileShare\`). Any file you drop there becomes available to your friend.

### Step 4 — Share your Tailscale IP
Tell your friend your Tailscale IP (shown in the app). They visit:
```
http://100.x.x.x:8765
```
...in their browser to see and download your files. You do the same with their IP.

---

## Part 4 — Optional: Set a PIN

To require a password before anyone can see or download your files, start the app with a PIN:

```
python fileshare.py --pin mysecretpin
```

Or edit line 10 of `fileshare.py` and set `DEFAULT_PIN = "yourpin"`.

---

## Firewall Note (Windows)

The first time you run the app, Windows may show a firewall prompt asking if Python can access the network. Click **Allow** (or allow on "Private networks" at minimum). Without this, your friend won't be able to reach your server.

If you don't see the prompt and connections aren't working, manually add an exception:
1. Search "Windows Defender Firewall with Advanced Security"
2. Inbound Rules → New Rule → Port → TCP → 8765 → Allow

---

## Quick Reference

| Action | How |
|---|---|
| Start sharing | Double-click `START_FILESHARE.bat` |
| Add a file to share | Drop it into `C:\Users\YourName\FileShare\` |
| Access your friend's files | Go to `http://<their-tailscale-ip>:8765` in browser |
| Find your Tailscale IP | Shown in the app, or click Tailscale tray icon |
| Stop sharing | Close the terminal window |
| Change PIN | Run `python fileshare.py --pin newpin` |
