"""utils/media_text.py: rasm ichidagi yozuv (OCR) va QR-kod reklama tekshiruvidan o'tadi."""
import cv2
import numpy as np
import pytest
from aiogram.methods import DeleteMessage

import database as dbm
from tests import telegram_fakes as tf
from tests.test_nsfw import PHOTO, USER, FakeDetector, deleted, post
from utils import ads, media_text, nsfw


def _png(image) -> bytes:
    return cv2.imencode(".png", image)[1].tobytes()


def _qr(data: str) -> bytes:
    code = cv2.resize(cv2.QRCodeEncoder.create().encode(data), (300, 300), interpolation=cv2.INTER_NEAREST)
    return _png(cv2.copyMakeBorder(code, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255))


@pytest.fixture(autouse=True)
def clean_model(monkeypatch):
    monkeypatch.setattr(nsfw, "_detector", FakeDetector())  # 18+ emas: faqat yozuv tekshiriladi
    monkeypatch.setattr(nsfw, "_detector_failed", False)


@pytest.fixture
def image(monkeypatch):
    """Telegram'dan "yuklanadigan" rasm (`image.data`) va yuklashlar soni."""

    class Img:
        data = _png(np.full((300, 300, 3), 255, np.uint8))
        downloads = 0

    img = Img()

    async def fake(bot, file_id):
        img.downloads += 1
        return img.data

    monkeypatch.setattr(nsfw, "_download", fake)
    return img


@pytest.fixture
def ocr(monkeypatch):
    """Tesseract o'rniga: `ocr.text` qaytariladi."""

    class Ocr:
        text = ""
        calls = 0

    o = Ocr()

    def fake(img) -> str:
        o.calls += 1
        return o.text

    monkeypatch.setattr(media_text, "read_text", fake)
    return o


@pytest.fixture
def ai(monkeypatch):
    calls: list = []

    async def fake(messages, **kw):
        calls.append(messages)
        return "OK"

    monkeypatch.setattr(ads, "ask_ai", fake)
    return calls


class TestImageText:
    async def test_promo_text_in_a_picture_is_deleted_without_ai(self, dp, bot, session, image, ocr, ai):
        ocr.text = "Kanalimizga obuna bo'ling! t.me/pul_ishlash"
        await post(dp, bot, {"photo": PHOTO})
        assert deleted(session) == [800] and ai == []

    async def test_ordinary_meme_text_costs_no_ai_call(self, dp, bot, session, image, ocr, ai):
        ocr.text = "When the code works on the first try"
        await post(dp, bot, {"photo": PHOTO})
        assert deleted(session) == [] and ai == []

    async def test_doubtful_text_goes_to_ai_marked_as_image_text(self, dp, bot, session, image, ocr, ai):
        ocr.text = "Zakaz uchun +998 90 123 45 67"
        await post(dp, bot, {"photo": PHOTO, "caption": "Qarang"})
        assert len(ai) == 1
        sent = ai[0][1]["content"]
        assert "Qarang\n🖼\nZakaz uchun" in sent

    async def test_same_picture_is_read_once(self, dp, bot, session, image, ocr, ai):
        ocr.text = "salom dunyo"
        await post(dp, bot, {"photo": PHOTO})
        await post(dp, bot, {"photo": PHOTO}, message_id=801)
        assert ocr.calls == 1 and image.downloads == 1  # 18+ tekshiruvi va o'qish bitta yuklashni bo'lishadi
        assert await dbm.get_media_text("u-photo") == "salom dunyo"

    async def test_bot_admin_picture_is_not_read(self, dp, bot, session, image, ocr):
        await post(dp, bot, {"photo": PHOTO}, user=tf.ADMIN_ID)
        assert ocr.calls == 0 and image.downloads == 0


class TestQrCode:
    async def test_qr_invite_link_is_deleted(self, dp, bot, session, image, ocr, ai):
        image.data = _qr("https://t.me/+SpamInvite123")
        await post(dp, bot, {"photo": PHOTO})
        assert deleted(session) == [800] and ai == []

    async def test_qr_adult_site_is_dangerous(self, dp, bot, session, image, ocr, ai):
        image.data = _qr("https://www.pornhub.com/x")
        await post(dp, bot, {"photo": PHOTO})
        assert deleted(session) == [800]

    def test_qr_is_read_even_without_tesseract(self, monkeypatch):
        monkeypatch.setattr(media_text, "_ocr_missing", True)
        monkeypatch.setattr(media_text, "_langs", None)
        img = cv2.imdecode(np.frombuffer(_qr("https://example.com/promo"), np.uint8), cv2.IMREAD_COLOR)
        assert media_text._extract([img]) == "https://example.com/promo"


class TestTesseractMissing:
    def test_missing_binary_disables_ocr_quietly(self, monkeypatch):
        monkeypatch.setattr(media_text, "_ocr_missing", False)
        monkeypatch.setattr(media_text, "_langs", None)
        monkeypatch.setattr(media_text.shutil, "which", lambda name: None)
        assert media_text.read_text(np.full((50, 50, 3), 255, np.uint8)) == ""
        assert media_text._ocr_missing is True
