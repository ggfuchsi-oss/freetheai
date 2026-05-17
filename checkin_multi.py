#!/usr/bin/env python3
"""
checkin_multi.py - Daily /checkin for multiple Discord accounts.

Add tokens to the TOKENS list below, one per FreeTheAI account.
"""
import os, time, random, string, json, threading, datetime
import urllib.request, urllib.error
import websocket
from http.server import HTTPServer, BaseHTTPRequestHandler

def _start_http():
    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        def do_HEAD(self):
            self.send_response(200); self.end_headers()
        def log_message(self, *a): pass
    port = int(os.environ.get("PORT", 10000))
    print(f"[http] binding port {port}", flush=True)
    threading.Thread(target=HTTPServer(("0.0.0.0", port), _H).serve_forever, daemon=True).start()

_start_http()

# ── Add your Discord user tokens here ────────────────────────────────────────
# Set DISCORD_TOKENS as a comma-separated list in Render env vars
# e.g. DISCORD_TOKENS=token1,token2,token3
_raw = os.environ.get("DISCORD_TOKENS", "")
TOKENS = [t.strip() for t in _raw.split(",") if t.strip()]
# ─────────────────────────────────────────────────────────────────────────────

CHANNEL_ID      = "1499062614133838087"
GUILD_ID        = "1461555807731585158"
APPLICATION_ID  = "1473157169665802300"
CHECKIN_ID      = "1502115111232340039"
CHECKIN_VERSION = "1502115111781929026"


def nonce():
    return str((int(time.time() * 1000) - 1420070400000) << 22)

def session_id():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=16))

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

def seconds_until_utc_midnight():
    now = utc_now()
    midnight = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (midnight - now).total_seconds()


def do_checkin(token: str, label: str) -> bool:
    payload = json.dumps({
        "type": 2,
        "application_id": APPLICATION_ID,
        "guild_id": GUILD_ID,
        "channel_id": CHANNEL_ID,
        "session_id": session_id(),
        "analytics_location": "slash_ui",
        "nonce": nonce(),
        "data": {
            "version": CHECKIN_VERSION,
            "id": CHECKIN_ID,
            "name": "checkin",
            "type": 1,
            "guild_id": GUILD_ID,
            "options": [],
            "attachments": [],
            "application_command": {
                "id": CHECKIN_ID,
                "application_id": APPLICATION_ID,
                "version": CHECKIN_VERSION,
                "name": "checkin",
                "name_localized": "checkin",
                "description": "Unlock your API key for the current UTC day",
                "description_localized": "Unlock your API key for the current UTC day",
                "type": 1,
                "guild_id": GUILD_ID,
                "options": [],
                "integration_types": [0],
            },
        },
    }).encode()

    req = urllib.request.Request(
        "https://discord.com/api/v9/interactions",
        data=payload,
        headers={
            "Authorization": token,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[{label}] /checkin sent (HTTP {resp.status})", flush=True)
            return True
    except urllib.error.HTTPError as e:
        print(f"[{label}] HTTP {e.code}: {e.read().decode(errors='replace')[:200]}", flush=True)
        return False
    except Exception as e:
        print(f"[{label}] Error: {e}", flush=True)
        return False


def checkin_all():
    for i, token in enumerate(TOKENS):
        label = f"account-{i+1}"
        do_checkin(token, label)
        time.sleep(2)  # small delay between accounts


def main():
    print(f"[checkin_multi] Starting with {len(TOKENS)} accounts", flush=True)
    checkin_all()

    while True:
        wait = seconds_until_utc_midnight()
        eta = utc_now() + datetime.timedelta(seconds=wait)
        print(f"[checkin_multi] Next checkin: {eta.strftime('%Y-%m-%d %H:%M:%S')} UTC ({wait/3600:.1f}h)", flush=True)
        time.sleep(wait + 5)
        checkin_all()


if __name__ == "__main__":
    main()
