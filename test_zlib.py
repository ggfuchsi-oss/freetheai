#!/usr/bin/env python3
"""Test gateway with zlib-stream compression — should receive INTERACTION_MODAL_CREATE."""
import os, time, json, random, string, threading, zlib
import urllib.request
import websocket

DISCORD_TOKEN  = os.environ["DISCORD_TOKEN"]
CHANNEL_ID     = "1473159205048553705"
GUILD_ID       = "1461555807731585158"
APPLICATION_ID = "1473157169665802300"

_checkin_id      = None
_checkin_version = None
_inflator        = zlib.decompressobj()
_buf             = bytearray()
_gw_session_id   = None

def nonce():
    return str((int(time.time() * 1000) - 1420070400000) << 22)

def session_id():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=16))

def discover():
    global _checkin_id, _checkin_version
    req = urllib.request.Request(
        f"https://discord.com/api/v9/guilds/{GUILD_ID}/application-command-index?limit=200",
        headers={"Authorization": DISCORD_TOKEN, "User-Agent": "Mozilla/5.0"},
        method="GET",
    )
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    for cmd in data.get("application_commands", []):
        if cmd.get("application_id") == APPLICATION_ID and cmd.get("name") == "checkin":
            _checkin_id = cmd["id"]
            _checkin_version = cmd["version"]
            print(f"[discover] id={_checkin_id}")
            return True
    return False

def send_checkin():
    payload = json.dumps({
        "type": 2, "application_id": APPLICATION_ID,
        "guild_id": GUILD_ID, "channel_id": CHANNEL_ID,
        "session_id": _gw_session_id or session_id(), "analytics_location": "slash_ui",
        "nonce": nonce(),
        "data": {
            "version": _checkin_version, "id": _checkin_id,
            "name": "checkin", "type": 1, "guild_id": GUILD_ID,
            "options": [], "attachments": [],
            "application_command": {
                "id": _checkin_id, "application_id": APPLICATION_ID,
                "version": _checkin_version, "name": "checkin",
                "type": 1, "guild_id": GUILD_ID,
                "options": [], "integration_types": [0],
            },
        },
    }).encode()
    req = urllib.request.Request(
        "https://discord.com/api/v9/interactions", data=payload,
        headers={"Authorization": DISCORD_TOKEN, "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            print(f"[send] HTTP {r.status}")
    except Exception as e:
        print(f"[send] Error: {e}")

def on_message(ws, raw):
    global _buf
    # Accumulate compressed chunks; flush when zlib suffix arrives
    if isinstance(raw, bytes):
        _buf.extend(raw)
        if len(raw) < 4 or raw[-4:] != b'\x00\x00\xff\xff':
            return
        try:
            data = json.loads(_inflator.decompress(_buf))
        except Exception as e:
            print(f"[zlib] decompress error: {e}")
            return
        finally:
            _buf.clear()
    else:
        try:
            data = json.loads(raw)
        except Exception:
            return

    op = data.get("op")
    t  = data.get("t")

    if op == 10:
        interval = data["d"]["heartbeat_interval"]
        def hb():
            while True:
                time.sleep(interval / 1000)
                try: ws.send(json.dumps({"op": 1, "d": None}))
                except: break
        threading.Thread(target=hb, daemon=True).start()
        ws.send(json.dumps({
            "op": 2,
            "d": {
                "token": DISCORD_TOKEN, "intents": 0,
                "properties": {"os": "windows", "browser": "discord", "device": "desktop"},
            },
        }))

    elif op == 0 and t == "READY":
        global _gw_session_id
        _gw_session_id = data["d"].get("session_id")
        print(f"[gateway] READY (session={_gw_session_id[:8]}...) — sending /checkin in 1s...")
        threading.Thread(target=lambda: (time.sleep(1), send_checkin()), daemon=True).start()

    elif op == 0:
        if t and "INTERACTION" in t:
            print(f"\n{'='*60}\nEVENT: {t}\n{json.dumps(data, indent=2)}\n{'='*60}")
        elif isinstance(data.get("d"), dict) and data["d"].get("custom_id"):
            print(f"\n[!] custom_id EVENT: {t}\n{json.dumps(data, indent=2)[:800]}")

def on_error(ws, e): print(f"[error] {e}")
def on_close(ws, *_): print("[closed]")

if __name__ == "__main__":
    discover()
    print("[gateway] connecting with zlib-stream compression...")
    websocket.WebSocketApp(
        "wss://gateway.discord.gg/?v=10&encoding=json&compress=zlib-stream",
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    ).run_forever()
