#!/usr/bin/env python3
import os, time, random, string, json, threading
import urllib.request, urllib.error, datetime
import websocket

DISCORD_TOKEN   = os.environ["DISCORD_TOKEN"]
CHANNEL_ID      = "1499062614133838087"
GUILD_ID        = "1461555807731585158"
APPLICATION_ID  = "1473157169665802300"
CHECKIN_ID      = "1502115111232340039"
CHECKIN_VERSION = "1502115111781929026"

_waiting_for_response = False

def nonce():
    return str((int(time.time() * 1000) - 1420070400000) << 22)

def session_id():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=16))

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

def do_checkin():
    global _waiting_for_response
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
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://discord.com/api/v9/interactions",
        data=payload,
        headers={
            "Authorization": DISCORD_TOKEN,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[checkin] /checkin gesendet ({resp.status})", flush=True)
            _waiting_for_response = True
            return True
    except urllib.error.HTTPError as e:
        print(f"[checkin] HTTP {e.code}: {e.read().decode(errors='replace')[:200]}", flush=True)
        return False
    except Exception as e:
        print(f"[checkin] Error: {e}", flush=True)
        return False

def seconds_until_utc_midnight():
    now = utc_now()
    midnight = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (midnight - now).total_seconds()

def start_gateway():
    def send_heartbeat(ws, interval):
        while True:
            time.sleep(interval / 1000)
            try:
                ws.send(json.dumps({"op": 1, "d": None}))
            except:
                break

    def on_open(ws):
        print("[gateway] Verbunden", flush=True)

    def on_message(ws, message):
        global _waiting_for_response
        data = json.loads(message)
        op = data.get("op")
        t = data.get("t")

        if op == 10:
            interval = data["d"]["heartbeat_interval"]
            threading.Thread(target=send_heartbeat, args=(ws, interval), daemon=True).start()
            ws.send(json.dumps({
                "op": 2,
                "d": {
                    "token": DISCORD_TOKEN,
                    "intents": 512,
                    "properties": {"os": "windows", "browser": "discord", "device": "desktop"},
                }
            }))

        elif op == 0 and t == "MESSAGE_CREATE":
            msg = data["d"]
            if msg.get("channel_id") != CHANNEL_ID or not _waiting_for_response:
                return
            author = msg.get("author", {})
            if author.get("bot") or msg.get("interaction"):
                content = msg.get("content", "")
                print(f"[bot] {author.get('username', '?')}: {content}", flush=True)
                for embed in msg.get("embeds", []):
                    if embed.get("description"):
                        print(f"      {embed['description']}", flush=True)
                _waiting_for_response = False

    def on_error(ws, error):
        print(f"[gateway] Error: {error}", flush=True)

    def on_close(ws, code, msg):
        print(f"[gateway] Getrennt, reconnecting...", flush=True)
        time.sleep(5)
        start_gateway()

    websocket.WebSocketApp(
        "wss://gateway.discord.gg/?v=10&encoding=json",
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    ).run_forever()

def main():
    print("[checkin] Starting...", flush=True)
    threading.Thread(target=start_gateway, daemon=True).start()
    time.sleep(3)
    do_checkin()
    while True:
        wait = seconds_until_utc_midnight()
        eta = utc_now() + datetime.timedelta(seconds=wait)
        print(f"[checkin] Naechster Checkin: {eta.strftime('%Y-%m-%d %H:%M:%S')} UTC ({wait/3600:.1f}h)", flush=True)
        time.sleep(wait + 5)
        do_checkin()

if __name__ == "__main__":
    main()
