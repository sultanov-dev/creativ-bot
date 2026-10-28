"""Rasm ichidagi yozuv va QR-kod: o'qilgan matn va havolalar oddiy xabar matni kabi reklama tekshiruvidan o'tadi.

- QR-kod: OpenCV QRCodeDetector (qo'shimcha kutubxonasiz), bir rasmda bir nechtasi ham o'qiladi.
- Yozuv (OCR): Tesseract (github.com/tesseract-ocr/tesseract, Apache-2.0) — serverda alohida dastur sifatida
  ishlaydi (Docker image'da o'rnatilgan), o'zbek (lotin va kirill), rus va ingliz tillari. Rasm hech qayerga
  yuborilmaydi. Tesseract topilmasa, faqat QR-kod o'qiladi (logda bir marta ogohlantirish).

Natija faylning file_unique_id'si bo'yicha bazada saqlanadi: bir xil rasm/stiker qayta o'qilmaydi.
"""
import asyncio
import logging
import shutil
import subprocess

from aiogram import Bot
from aiogram.types import Message

from database import get_media_text, save_media_text
from utils import nsfw

logger = logging.getLogger(__name__)

WANTED_LANGS = ("uzb", "uzb_cyrl", "rus", "eng")
OCR_TIMEOUT = 20
OCR_MAX_SIDE = 1600  # kichik yozuv yaxshi o'qilishi uchun kattalashtiriladi, katta rasm kichraytiriladi
OCR_MIN_SIDE = 800
MAX_IMAGES = 2  # videodan ko'pi bilan 2 kadr o'qiladi
MAX_TEXT = 1500

_langs: str | None = None
_ocr_missing = False
_ocr_slots = asyncio.Semaphore(1)  # Tesseract protsessorni band qiladi: navbat bilan


def _languages() -> str | None:
    """Tesseract'da bor tillar ("uzb+rus+eng"); dastur yo'q bo'lsa None."""
    global _langs, _ocr_missing
    if _langs is None and not _ocr_missing:
        exe = shutil.which("tesseract")
        if exe is None:
            _ocr_missing = True
            logger.warning("Tesseract topilmadi: rasmdagi yozuv o'qilmaydi, faqat QR-kod")
            return None
        try:
            out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError) as e:
            _ocr_missing = True
            logger.warning("Tesseract ishlamadi: %r", e)
            return None
        available = set(out.split())
        _langs = "+".join(lang for lang in WANTED_LANGS if lang in available) or "eng"
    return _langs


def _prepare(image):
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    h, w = gray.shape[:2]
    side = max(h, w)
    scale = OCR_MAX_SIDE / side if side > OCR_MAX_SIDE else (OCR_MIN_SIDE / side if side < OCR_MIN_SIDE else 1.0)
    if scale != 1.0:
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
    return gray


def read_qr(image) -> list[str]:
    """Rasmdagi QR-kodlar matni. Bir nechta kodni o'qish ba'zan bitta kodni topmaydi: unda bittalik usul ham sinaladi."""
    import cv2

    detector = cv2.QRCodeDetector()
    found: list[str] = []
    try:
        ok, decoded, _, _ = detector.detectAndDecodeMulti(image)
        if ok:
            found = [d for d in decoded if d]
        if not found:
            single, _, _ = detector.detectAndDecode(image)
            found = [single] if single else []
    except cv2.error:
        return []
    return found


def read_text(image) -> str:
    langs = _languages()
    if langs is None:
        return ""
    import cv2

    ok, png = cv2.imencode(".png", _prepare(image))
    if not ok:
        return ""
    try:
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", langs, "--psm", "3"],
            input=png.tobytes(), capture_output=True, timeout=OCR_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("OCR ishlamadi: %r", e)
        return ""
    text = result.stdout.decode("utf-8", "ignore")
    return " ".join(text.split())


def _extract(images: list) -> str:
    """Rasmlardagi QR havolalar va yozuv bitta matnda (avval QR: havola aniq o'qiladi)."""
    qr: list[str] = []
    words: list[str] = []
    for image in images[:MAX_IMAGES]:
        qr += [q for q in read_qr(image) if q not in qr]
        text = read_text(image)
        if text and text not in words:
            words.append(text)
    return "\n".join([*qr, *words])[:MAX_TEXT]


async def extract(bot: Bot, message: Message) -> str:
    """Xabardagi rasm/stiker/video muqovasidagi QR-kod va yozuv ("" — yo'q yoki o'qib bo'lmadi)."""
    ref = nsfw.media_of(message)
    if ref is None:
        return ""
    cached = await get_media_text(ref.unique_id)
    if cached is not None:
        return cached
    frames = await nsfw.frames_of(bot, ref)
    if not frames:
        return ""
    async with _ocr_slots:
        text = await asyncio.to_thread(_extract, frames)
    logger.info("Rasmdagi yozuv: %s belgi", len(text))  # matnning o'zi logga yozilmaydi (shaxsiy bo'lishi mumkin)
    await save_media_text(ref.unique_id, text)
    return text
