"""Headless Claude fallback, ONLY when local OCR can't read the store name or date.
Sends only the receipt's first two strips (where store + date are printed) to `claude -p`
with the Read tool only, no MCP servers, no plugins, no session persistence."""
from __future__ import annotations

import json
import os
import re
import subprocess

CLAUDE = os.environ.get("RECEIPT_BOT_CLAUDE", os.path.expanduser("~/.local/bin/claude"))
MODEL = os.environ.get("RECEIPT_BOT_CLAUDE_MODEL", "sonnet")
TIMEOUT = int(os.environ.get("RECEIPT_BOT_CLAUDE_TIMEOUT", "300"))
MAX_IMAGES = 4

PROMPT = """You are reading the top of a scanned paper store receipt.
Use the Read tool to view each of these image files (consecutive horizontal strips, top to bottom):
{files}

Fields needed: {fields}.
Reply with ONLY one JSON object, no prose:
{{"vendor": "store name as printed, e.g. FoodMaxx" or null, "date": "YYYY-MM-DD purchase date" or null}}"""


def ask(images: list[str], fields: list[str], cwd: str, log=print) -> dict:
    images = images[:MAX_IMAGES]
    prompt = PROMPT.format(files="\n".join(images), fields=", ".join(fields))
    cmd = [CLAUDE, "-p", prompt, "--model", MODEL, "--tools", "Read", "--allowedTools", "Read",
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--no-session-persistence",
           "--disable-slash-commands", "--output-format", "json", "--max-turns", str(len(images) + 4)]
    env = dict(os.environ)
    env["PATH"] = os.path.expanduser("~/.local/bin") + ":" + env.get("PATH", "/usr/bin:/bin")
    log(f"claude fallback: {len(images)} image(s), fields={fields}, model={MODEL}")
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as e:
        log(f"claude fallback failed: {type(e).__name__}")
        return {}
    try:
        outer = json.loads(r.stdout)
        text = outer.get("result", "") if isinstance(outer, dict) else ""
        cost = outer.get("total_cost_usd") if isinstance(outer, dict) else None
    except ValueError:
        text, cost = r.stdout, None
    m = re.search(r"\{.*\}", text or "", re.S)
    if r.returncode != 0 or not m:
        log(f"claude fallback: no usable answer (rc={r.returncode}) {r.stderr.strip()[-200:]}")
        return {}
    try:
        ans = json.loads(m.group(0))
    except ValueError:
        log("claude fallback: answer was not JSON")
        return {}
    log(f"claude fallback answer: {json.dumps(ans)}" + (f" (cost ${cost:.4f})" if cost else ""))
    return ans if isinstance(ans, dict) else {}
