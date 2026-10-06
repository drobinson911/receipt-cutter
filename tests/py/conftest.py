import os
import sys

import numpy as np
import pytest
from PIL import Image, ImageDraw

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

# The real ScanSnap test receipt lives OUTSIDE git (public repo, personal data).
REAL_FIXTURE = os.path.expanduser(os.environ.get("RECEIPT_FIXTURE", "~/.local/share/receipt-bot/fixtures/10062026.jpg"))


def synthetic_receipt(height=8000, width=600, line_h=20, pitch=34, top=40, seed=1):
    """White strip with black 'text lines' (bars of random width) every `pitch` px."""
    rng = np.random.default_rng(seed)
    img = Image.new("L", (width, height), 255)
    d = ImageDraw.Draw(img)
    y = top
    while y + line_h < height - 20:
        w = int(rng.integers(80, width - 40))
        d.rectangle((20, y, 20 + w, y + line_h - 1), fill=0)
        y += pitch
    return img


@pytest.fixture
def receipt_img():
    return synthetic_receipt()


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Isolated bot environment: local 'Drive' root, state, work, out, lock, ops dir; no Discord,
    no responder trigger. Modules read these at import → reload them."""
    root = tmp_path / "drive" / "Receipts"
    root.mkdir(parents=True)
    env = {
        "RECEIPT_BOT_DRIVE_ROOT": str(root),
        "RECEIPT_BOT_STATE": str(tmp_path / "state.json"),
        "RECEIPT_BOT_WORK": str(tmp_path / "work"),
        "RECEIPT_BOT_OUT": str(tmp_path / "out"),
        "RECEIPT_BOT_LOCK": str(tmp_path / "run.lock"),
        "RECEIPT_BOT_NO_DISCORD": "1",
        "RECEIPT_BOT_NO_TRIGGER": "1",
        "UAS_OPS_DIR": str(tmp_path / "ops"),
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import importlib
    from receipt_bot import bot, drive, ops, state
    for m in (drive, state, ops, bot):
        importlib.reload(m)
    yield {"root": root, "tmp": tmp_path, "bot": bot, "drive": drive, "state": state, "ops": ops}
    for k in env:
        monkeypatch.delenv(k, raising=False)
    for m in (drive, state, ops, bot):
        importlib.reload(m)
