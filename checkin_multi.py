#!/usr/bin/env python3
"""
checkin_multi.py - Daily /checkin for multiple Discord accounts.

DISCORD_TOKENS format: token1:apikey1,token2:apikey2,...
OPENROUTER_API_KEY:    your OpenRouter key (for solving modal questions)
"""
import os, time, random, string, json, threading, datetime, re, zlib
import urllib.request, urllib.error
import websocket
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── HTTP keep-alive for Render ─────────────────────────────────────────────────
def _start_http():
    class _H(BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        def do_HEAD(self): self.send_response(200); self.end_headers()
        def log_message(self, *a): pass
    port = int(os.environ.get("PORT", 10000))
    print(f"[http] binding port {port}", flush=True)
    threading.Thread(target=HTTPServer(("0.0.0.0", port), _H).serve_forever, daemon=True).start()

_start_http()

# ── Config ─────────────────────────────────────────────────────────────────────
CHANNEL_ID      = "1473159205048553705"
GUILD_ID        = "1461555807731585158"
APPLICATION_ID  = "1473157169665802300"
OPENROUTER_KEY  = os.environ.get("OPENROUTER_API_KEY", "")
ZENLLM_KEY      = os.environ.get("ZENLLM_API_KEY", "")

_checkin_id      = None
_checkin_version = None
_discover_lock   = threading.Lock()

# ── Parse accounts ─────────────────────────────────────────────────────────────
# Format: token1:apikey1,token2:apikey2
ACCOUNTS = []
for _entry in os.environ.get("DISCORD_TOKENS", "").split(","):
    _entry = _entry.strip()
    if not _entry:
        continue
    if ":" in _entry:
        _tok, _key = _entry.split(":", 1)
        ACCOUNTS.append({"token": _tok.strip(), "api_key": _key.strip()})
    else:
        ACCOUNTS.append({"token": _entry, "api_key": ""})

# ── Helpers ────────────────────────────────────────────────────────────────────
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

def _http(url, data=None, headers=None, method=None):
    body = json.dumps(data).encode() if data else None
    if method is None:
        method = "POST" if body else "GET"
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}

def discord_headers(token):
    return {
        "Authorization": token,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

# ── AI question solver ─────────────────────────────────────────────────────────
def _openrouter(messages: list, max_tokens: int = 50) -> str:
    if ZENLLM_KEY:
        url   = "https://api.zenllm.org/v1/chat/completions"
        key   = ZENLLM_KEY
        model = "xiaomi/mimo-v2.5-pro-full"
    else:
        url   = "https://openrouter.ai/api/v1/chat/completions"
        key   = OPENROUTER_KEY
        model = "openai/gpt-4o-mini"

    resp = _http(
        url,
        data={"model": model, "messages": messages, "max_tokens": max_tokens},
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    return resp["choices"][0]["message"]["content"].strip()


def ask_ai(label: str, placeholder: str) -> str:
    if not OPENROUTER_KEY and not ZENLLM_KEY:
        print("[ai] No AI key set, trying regex fallback", flush=True)
        return _regex_fallback(label)

    print(f"[ai] Solving — label={label!r} placeholder={placeholder!r}", flush=True)
    try:
        # Step 1: Solver — understand the question and reason out an answer
        raw_answer = _openrouter([
            {
                "role": "system",
                "content": (
                    "You are solving a form field question. "
                    "You will be given the field label and its placeholder text. "
                    "Figure out what answer is expected and respond with just that answer. "
                    "Think step by step if needed, but keep it short."
                ),
            },
            {
                "role": "user",
                "content": f"Label: {label}\nPlaceholder: {placeholder}",
            },
        ], max_tokens=50)
        print(f"[ai] Solver raw: {raw_answer!r}", flush=True)

        # Step 2: Formatter — strip it down to the exact value to type
        final = _openrouter([
            {
                "role": "system",
                "content": (
                    "You are a formatter. You receive a form field (label + placeholder) "
                    "and a solved answer. Output ONLY the exact text to type into the field. "
                    "The placeholder often shows the expected format — match it. "
                    "Single word or number. No punctuation unless part of the answer. "
                    "No explanation. Nothing else."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Label: {label}\n"
                    f"Placeholder: {placeholder}\n"
                    f"Solved answer: {raw_answer}"
                ),
            },
        ], max_tokens=10)
        print(f"[ai] Formatter final: {final!r}", flush=True)
        return final

    except Exception as e:
        print(f"[ai] Error: {e}, trying regex fallback", flush=True)
        return _regex_fallback(label)


def _regex_fallback(question: str) -> str:
    nums = re.findall(r'\d+', question)
    if len(nums) >= 2:
        return str(min(int(n) for n in nums))
    return ""

# ── Command discovery ──────────────────────────────────────────────────────────
def discover_checkin_command(token: str) -> bool:
    global _checkin_id, _checkin_version
    with _discover_lock:
        if _checkin_id:
            return True
        try:
            data = _http(
                f"https://discord.com/api/v9/guilds/{GUILD_ID}/application-command-index?limit=200",
                headers=discord_headers(token),
                method="GET",
            )
            for cmd in data.get("application_commands", []):
                if cmd.get("application_id") == APPLICATION_ID and cmd.get("name") == "checkin":
                    _checkin_id = cmd["id"]
                    _checkin_version = cmd["version"]
                    print(f"[discover] /checkin id={_checkin_id} version={_checkin_version}", flush=True)
                    return True
            print("[discover] /checkin not found in guild!", flush=True)
            return False
        except Exception as e:
            print(f"[discover] Error: {e}", flush=True)
            return False

# ── Send /checkin slash command ────────────────────────────────────────────────
def send_checkin_command(token: str, label: str, gw_session: str = None) -> bool:
    payload = {
        "type": 2,
        "application_id": APPLICATION_ID,
        "guild_id": GUILD_ID,
        "channel_id": CHANNEL_ID,
        "session_id": gw_session or session_id(),
        "analytics_location": "slash_ui",
        "nonce": nonce(),
        "data": {
            "version": _checkin_version,
            "id": _checkin_id,
            "name": "checkin",
            "type": 1,
            "guild_id": GUILD_ID,
            "options": [],
            "attachments": [],
            "application_command": {
                "id": _checkin_id,
                "application_id": APPLICATION_ID,
                "version": _checkin_version,
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
    }
    try:
        req = urllib.request.Request(
            "https://discord.com/api/v9/interactions",
            data=json.dumps(payload).encode(),
            headers=discord_headers(token),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[{label}] /checkin sent (HTTP {resp.status})", flush=True)
            return True
    except urllib.error.HTTPError as e:
        print(f"[{label}] HTTP {e.code}: {e.read().decode(errors='replace')[:200]}", flush=True)
        return False
    except Exception as e:
        print(f"[{label}] Error: {e}", flush=True)
        return False

# ── Submit modal ───────────────────────────────────────────────────────────────
def submit_modal(token: str, api_key: str, modal: dict, label: str) -> bool:
    # INTERACTION_MODAL_CREATE has custom_id + components directly (no data wrapper)
    custom_id = modal.get("custom_id", "")
    rows      = modal.get("components", [])

    filled = []
    for row in rows:
        filled_row = {"type": 1, "components": []}
        for comp in row.get("components", []):
            comp_label       = comp.get("label", "")
            comp_placeholder = comp.get("placeholder", "")
            hint = (comp_label + " " + comp_placeholder).lower()

            if comp.get("custom_id") == "checkin_api_key" or "api" in hint or "key" in hint:
                value = api_key
            else:
                value = ask_ai(comp_label, comp_placeholder)

            print(f"[{label}] Field '{comp_label}' → '{value}'", flush=True)
            filled_row["components"].append({
                "type": 4,
                "custom_id": comp.get("custom_id", ""),
                "value": value,
            })
        filled.append(filled_row)

    payload = {
        "type": 5,
        "application_id": APPLICATION_ID,
        "guild_id": GUILD_ID,
        "channel_id": CHANNEL_ID,
        "session_id": session_id(),
        "nonce": nonce(),
        "data": {
            "custom_id": custom_id,
            "components": filled,
        },
    }
    try:
        req = urllib.request.Request(
            "https://discord.com/api/v9/interactions",
            data=json.dumps(payload).encode(),
            headers=discord_headers(token),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[{label}] Modal submitted (HTTP {resp.status})", flush=True)
            return True
    except urllib.error.HTTPError as e:
        print(f"[{label}] Modal HTTP {e.code}: {e.read().decode(errors='replace')[:200]}", flush=True)
        return False
    except Exception as e:
        print(f"[{label}] Modal error: {e}", flush=True)
        return False

# ── Full per-account checkin flow ──────────────────────────────────────────────
def checkin_account(token: str, api_key: str, label: str) -> bool:
    modal_event   = threading.Event()
    modal_payload = {}
    gw_done       = threading.Event()
    inflator      = zlib.decompressobj()
    buf           = bytearray()
    gw_session_id = [None]  # filled from READY event

    def send_heartbeat(ws, interval):
        while not gw_done.is_set():
            time.sleep(interval / 1000)
            try:
                ws.send(json.dumps({"op": 1, "d": None}))
            except Exception:
                break

    def on_message(ws, raw):
        nonlocal buf
        if isinstance(raw, bytes):
            buf.extend(raw)
            if len(raw) < 4 or raw[-4:] != b'\x00\x00\xff\xff':
                return
            try:
                data = json.loads(inflator.decompress(bytes(buf)))
            except Exception as e:
                print(f"[{label}] zlib error: {e}", flush=True)
                return
            finally:
                buf = bytearray()
        else:
            try:
                data = json.loads(raw)
            except Exception:
                return
        op = data.get("op")
        t  = data.get("t")

        if op == 10:
            interval = data["d"]["heartbeat_interval"]
            threading.Thread(target=send_heartbeat, args=(ws, interval), daemon=True).start()
            ws.send(json.dumps({
                "op": 2,
                "d": {
                    "token": token,
                    "intents": 0,
                    "properties": {"os": "windows", "browser": "discord", "device": "desktop"},
                },
            }))

        elif op == 0 and t == "READY":
            # capture real session_id so Discord routes the modal back to this connection
            gw_session_id[0] = data["d"].get("session_id", session_id())
            print(f"[{label}] Gateway ready (session={gw_session_id[0][:8]}...), sending /checkin...", flush=True)
            def _send():
                time.sleep(1)
                send_checkin_command(token, label, gw_session_id[0])
            threading.Thread(target=_send, daemon=True).start()

        elif op == 0 and not modal_event.is_set():
            d = data.get("d", {})
            if not isinstance(d, dict):
                return

            print(f"[{label}] Gateway event: {t}", flush=True)

            # INTERACTION_MODAL_CREATE: custom_id + components directly in d
            if d.get("custom_id") and d.get("components"):
                print(f"[{label}] Modal captured! (event={t})", flush=True)
                modal_payload.update(d)
                modal_event.set()

    def on_error(ws, error):
        print(f"[{label}] Gateway error: {error}", flush=True)

    def on_close(ws, *_):
        gw_done.set()

    ws = websocket.WebSocketApp(
        "wss://gateway.discord.gg/?v=10&encoding=json&compress=zlib-stream",
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    threading.Thread(target=ws.run_forever, daemon=True).start()

    if modal_event.wait(timeout=25):
        ws.close()
        time.sleep(0.5)
        return submit_modal(token, api_key, modal_payload, label)
    else:
        print(f"[{label}] Timeout — no modal received in 25s", flush=True)
        ws.close()
        return False

# ── Main loop ──────────────────────────────────────────────────────────────────
def checkin_all():
    if not ACCOUNTS:
        print("[checkin_multi] No accounts in DISCORD_TOKENS!", flush=True)
        return

    if not _checkin_id:
        if not discover_checkin_command(ACCOUNTS[0]["token"]):
            print("[checkin_multi] Could not discover /checkin command, aborting.", flush=True)
            return

    for i, acc in enumerate(ACCOUNTS):
        checkin_account(acc["token"], acc["api_key"], f"account-{i+1}")
        time.sleep(3)


def main():
    print(f"[checkin_multi] Starting with {len(ACCOUNTS)} accounts", flush=True)
    checkin_all()

    while True:
        wait = seconds_until_utc_midnight()
        eta  = utc_now() + datetime.timedelta(seconds=wait)
        print(f"[checkin_multi] Next checkin: {eta.strftime('%Y-%m-%d %H:%M:%S')} UTC ({wait/3600:.1f}h)", flush=True)
        time.sleep(wait + 5)
        checkin_all()


if __name__ == "__main__":
    main()
