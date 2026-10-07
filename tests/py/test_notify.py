"""Discord ping: the PDF always goes as a multipart file attachment (never a link)."""
import cut_receipt
from receipt_bot import notify


def _env(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("DISCORD_BOT_TOKEN=test-token\n")
    monkeypatch.setattr(notify, "ENV_FILE", str(env))
    monkeypatch.setenv("UAS_ALERT_CHANNEL", "123")
    monkeypatch.delenv("RECEIPT_BOT_NO_DISCORD", raising=False)
    monkeypatch.setattr("time.sleep", lambda s: None)


def _pdf(tmp_path, receipt_img):
    p = str(tmp_path / "20261006_Robinson_FoodMaxx.pdf")
    cut_receipt.cut(receipt_img, p, log=lambda *a: None)
    return p


def test_pdf_is_sent_as_multipart_attachment(monkeypatch, tmp_path, receipt_img):
    _env(monkeypatch, tmp_path)
    pdf = _pdf(tmp_path, receipt_img)
    seen = {}

    def fake_post(url, headers, body):
        seen.update(url=url, headers=headers, body=body)
        return {"id": "1", "attachments": [{"filename": "20261006_Robinson_FoodMaxx.pdf"}]}
    monkeypatch.setattr(notify, "_post", fake_post)
    assert notify.send("Receipt cut: 20261006_Robinson_FoodMaxx.pdf", attach=pdf, log=lambda *a: None)
    assert seen["url"].endswith("/channels/123/messages")
    assert seen["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="files[0]"; filename="20261006_Robinson_FoodMaxx.pdf"' in seen["body"]
    assert b'"content": "Receipt cut: 20261006_Robinson_FoodMaxx.pdf"' in seen["body"]
    assert open(pdf, "rb").read() in seen["body"]
    assert b"drive.google.com" not in seen["body"]


def test_unconfirmed_attachment_is_retried_once_then_false(monkeypatch, tmp_path, receipt_img):
    _env(monkeypatch, tmp_path)
    n = []
    monkeypatch.setattr(notify, "_post", lambda *a: n.append(1) or {"id": "1", "attachments": []})
    assert notify.send("x", attach=_pdf(tmp_path, receipt_img), log=lambda *a: None) is False
    assert len(n) == 2


def test_network_error_then_success(monkeypatch, tmp_path, receipt_img):
    _env(monkeypatch, tmp_path)
    calls = []

    def flaky(*a):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("reset")
        return {"id": "2", "attachments": [{"filename": "f.pdf"}]}
    monkeypatch.setattr(notify, "_post", flaky)
    assert notify.send("x", attach=_pdf(tmp_path, receipt_img), log=lambda *a: None)


def test_oversized_pdf_gets_a_smaller_discord_copy(monkeypatch, tmp_path, receipt_img):
    pdf = _pdf(tmp_path, receipt_img)
    import os
    size = os.path.getsize(pdf)
    monkeypatch.setattr(notify, "MAX_ATTACH", size - 1)
    small = notify.discord_copy(pdf, log=lambda *a: None)
    assert small and small != pdf and os.path.getsize(small) <= size - 1
    assert open(pdf, "rb").read()[:4] == b"%PDF" and os.path.getsize(pdf) == size   # Drive copy untouched
