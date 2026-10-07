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


def discord_copy(pdf: str, log=print) -> str | None:
    """A PDF that fits the bot upload cap. The Drive copy is never touched; only an oversized
    Discord copy is re-encoded (grayscale JPEG pages, same 300 dpi, same layout)."""
    if os.path.getsize(pdf) <= MAX_ATTACH:
        return pdf
    import subprocess
    import tempfile
    from PIL import Image
    tmp = tempfile.mkdtemp(prefix="receipt-discord-")
    subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", pdf, os.path.join(tmp, "p")], check=True, timeout=300)
    pages = [Image.open(os.path.join(tmp, f)).convert("L") for f in sorted(os.listdir(tmp)) if f.endswith(".png")]
    out = os.path.join(tmp, os.path.basename(pdf))
    for q in (75, 55, 40):
        pages[0].save(out, save_all=True, append_images=pages[1:], resolution=300.0, quality=q)
        if os.path.getsize(out) <= MAX_ATTACH:
            log(f"discord: {os.path.basename(pdf)} {os.path.getsize(pdf) / 1e6:.1f} MB → grayscale copy "
                f"{os.path.getsize(out) / 1e6:.1f} MB (q{q}) for the upload")
            return out
    return None


def _post(url: str, headers: dict, body: bytes) -> dict | None:
    req = urllib.request.Request(url, body, headers, method="POST")
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read() or b"{}") if 200 <= r.status < 300 else None


def send(text: str, attach: str | None = None, log=print) -> bool:
    """Post `text` (and the PDF `attach`, always as a file — never a link) to Donald's channel.
    One retry after 10 s. True only if Discord confirms the message (and the attachment)."""
    if os.environ.get("RECEIPT_BOT_NO_DISCORD"):
        log(f"discord (suppressed): {text}" + (f" [+ {os.path.basename(attach)}]" if attach else ""))
        return True
    tok, channel = _token(), _channel()
    if not tok or not channel:
        log("discord: no bot token/channel available — message logged only")
        return False
    url = f"https://discord.com/api/v10/channels/{channel}/messages"
    payload = {"content": text[:1900], "allowed_mentions": {"parse": []}}
    headers = {"Authorization": f"Bot {tok}", "User-Agent": "forge-receipt-bot/1.0"}
    file = discord_copy(attach, log) if attach else None
    if attach and file is None:
        payload["content"] = (text + f" (PDF {os.path.getsize(attach) / 1e6:.0f} MB is too big for Discord even "
                              "re-encoded; it's in Drive Cut/)")[:1900]
    if file:
        b = uuid.uuid4().hex
        fn = os.path.basename(attach)
        payload["attachments"] = [{"id": 0, "filename": fn}]
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
                f"Content-Type: application/json\r\n\r\n{json.dumps(payload)}\r\n"
                f"--{b}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"{fn}\"\r\n"
                f"Content-Type: application/pdf\r\n\r\n").encode() + open(file, "rb").read() + f"\r\n--{b}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={b}"
    else:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    import time
    for attempt in (1, 2):
        try:
            resp = _post(url, headers, body)
            got = [a.get("filename") for a in (resp or {}).get("attachments", [])]
            if resp is not None and (not file or got):
                log(f"discord: sent (message {resp.get('id')})" + (f" with attachment {got[0]}" if got else ""))
                return True
            log(f"discord: attempt {attempt}: Discord did not confirm the attachment")
        except Exception as e:  # noqa: BLE001 — never let a ping failure crash processing
            log(f"discord: attempt {attempt} FAILED ({type(e).__name__}: {str(e)[:120]})")
        if attempt == 1:
            time.sleep(10)
    return False
