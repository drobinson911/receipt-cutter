"""Discord pings to Donald — same channel + bot token as ~/bin/uas-alert.sh (the token is read
from the Discord plugin's .env at send time; it never appears in argv, logs or git).
Supports one file attachment (multipart upload)."""
from __future__ import annotations

import json
import os
import re
import urllib.request
import uuid

ALERT_SH = os.path.expanduser("~/bin/uas-alert.sh")


def _channel() -> str | None:
    """Donald's ops channel: $UAS_ALERT_CHANNEL, else the default baked into ~/bin/uas-alert.sh
    (single source of truth; kept out of this public repo)."""
    if os.environ.get("UAS_ALERT_CHANNEL"):
        return os.environ["UAS_ALERT_CHANNEL"]
    try:
        m = re.search(r'CHANNEL="\$\{UAS_ALERT_CHANNEL:-(\d+)\}"', open(ALERT_SH).read())
        return m[1] if m else None
    except OSError:
        return None
ENV_FILE = os.environ.get("UAS_ALERT_TOKEN_FILE", os.path.expanduser("~/.claude/channels/discord/.env"))
MAX_ATTACH = 9_500_000  # bot uploads cap at 10 MB on a non-boosted server


def _token() -> str | None:
    try:
        for ln in open(ENV_FILE):
            if ln.startswith("DISCORD_BOT_TOKEN="):
                return ln.split("=", 1)[1].strip() or None
    except OSError:
        return None
    return None


def send(text: str, attach: str | None = None, log=print) -> bool:
    if os.environ.get("RECEIPT_BOT_NO_DISCORD"):
        log(f"discord (suppressed): {text}")
        return True
    tok, channel = _token(), _channel()
    if not tok or not channel:
        log("discord: no bot token/channel available — message logged only")
        return False
    url = f"https://discord.com/api/v10/channels/{channel}/messages"
    payload = {"content": text[:1900], "allowed_mentions": {"parse": []}}
    headers = {"Authorization": f"Bot {tok}", "User-Agent": "forge-receipt-bot/1.0"}
    if attach and os.path.getsize(attach) <= MAX_ATTACH:
        b = uuid.uuid4().hex
        fn = os.path.basename(attach)
        payload["attachments"] = [{"id": 0, "filename": fn}]
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
                f"Content-Type: application/json\r\n\r\n{json.dumps(payload)}\r\n"
                f"--{b}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"{fn}\"\r\n"
                f"Content-Type: application/pdf\r\n\r\n").encode() + open(attach, "rb").read() + f"\r\n--{b}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={b}"
    else:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, body, headers, method="POST"), timeout=60) as r:
            ok = 200 <= r.status < 300
    except Exception as e:  # noqa: BLE001 — never let a ping failure crash processing
        log(f"discord: delivery FAILED ({type(e).__name__}: {str(e)[:120]})")
        return False
    log(f"discord: sent{' with ' + os.path.basename(attach) if attach and 'attachments' in payload else ''}")
    return ok
