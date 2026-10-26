import html
import logging
import re
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# Telegram HTML'dan faqat shu teglar o'tadi; qolgani matn sifatida escape qilinadi
ALLOWED_TAGS = {"b", "i", "u", "s", "code", "pre", "a"}
_CODE_TAGS = ("code", "pre")

_TOKEN = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)([^<>]*)>")
_HREF = re.compile(r"""\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
_URL_SPLIT = re.compile(r"(https?://\S+)")
_BULLET = re.compile(r"^([ \t]*)[-*•–—][ \t]+", re.MULTILINE)
_DASHES = re.compile(r"[-–—‑]")
# model ba'zan ruxsat etilgan teglarni ham escape qiladi (&lt;b&gt;, &#60;b&#62;, &amp;lt;b&amp;gt;, \u003cb\u003e):
# haqiqiy tegga qaytaramiz, lekin keyin baribir allowlist va havola tekshiruvidan o'tadi
_LT = r"(?:&(?:amp;)*(?:lt|#0*60|#x0*3c);|\\u003c)"
_GT = r"(?:&(?:amp;)*(?:gt|#0*62|#x0*3e);|\\u003e)"
_ESCAPED_TAG = re.compile(
    _LT + r"(/?(?:b|i|u|s|code|pre|a)(?:\s[^<>&]*)?)" + _GT, re.IGNORECASE
)
# sanitize'dan keyin ham ko'rinib qoladigan escape qilingan teg: modelning kutilmagan formati
_LEAKED_TAG = re.compile(r"&lt;/?(?:b|i|u|s|code|pre|a)\b", re.IGNORECASE)


def _safe_href(attrs: str) -> str | None:
    """Faqat https havola (tg://, javascript: va "google.com@evil" kabilar o'tmaydi)."""
    m = _HREF.search(attrs)
    if not m:
        return None
    url = html.unescape(m.group(1) if m.group(1) is not None else m.group(2)).strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if (
        parts.scheme != "https"
        or not parts.hostname
        or "@" in parts.netloc
        or re.search(r"\s", url)
    ):
        return None
    return url


def _text(seg: str, in_code: bool, line_start: bool) -> str:
    """Oddiy matn: tire/defis olib tashlanadi (URL va kod tegmaydi), keyin HTML-escape."""
    seg = html.unescape(seg)
    if not in_code:
        # birinchi qator boshi bo'lmasa, "- " ro'yxat belgisi deb hisoblanmasin
        marker = "\n" if line_start else "x"
        seg = _BULLET.sub(r"\1• ", marker + seg)[1:]
        seg = "".join(
            p if i % 2 else _DASHES.sub(" ", p)
            for i, p in enumerate(_URL_SPLIT.split(seg))
        )
    return html.escape(seg, quote=False)


def sanitize_html(text: str) -> str:
    """Model javobini xavfsiz Telegram HTML'ga aylantiradi.

    Ruxsat etilgan teglar (b i u s code pre a[https]) qoladi, teglar to'g'ri yopiladi,
    qolgan hamma narsa (jumladan <, & va notanish teglar) escape qilinadi. Ro'yxat
    belgisi "•" bo'ladi, qolgan tire/defislar probelga almashadi.
    """
    text = _ESCAPED_TAG.sub(r"<\1>", text)
    out: list[str] = []
    stack: list[str] = []
    line_start = True
    pos = 0

    def emit(seg: str) -> None:
        nonlocal line_start
        if not seg:
            return
        out.append(_text(seg, any(t in _CODE_TAGS for t in stack), line_start))
        line_start = seg.endswith("\n")

    for m in _TOKEN.finditer(text):
        emit(text[pos : m.start()])
        pos = m.end()
        closing, name, attrs = m.group(1), m.group(2).lower(), m.group(3)

        if name not in ALLOWED_TAGS:
            emit(m.group(0))
            continue
        if closing:
            if name in stack:
                while stack:
                    top = stack.pop()
                    out.append(f"</{top}>")
                    if top == name:
                        break
            continue
        # code/pre ichida boshqa teg bo'lmaydi (pre ichida code bundan mustasno)
        if stack and stack[-1] in _CODE_TAGS and not (stack[-1] == "pre" and name == "code"):
            continue
        if name == "a":
            href = _safe_href(attrs)
            if href is None or "a" in stack:
                continue
            out.append(f'<a href="{html.escape(href, quote=True)}">')
        else:
            out.append(f"<{name}>")
        stack.append(name)

    emit(text[pos:])
    out.extend(f"</{t}>" for t in reversed(stack))
    result = "".join(out).strip()
    if _LEAKED_TAG.search(result):
        logger.warning("AI javobida teg matn bo'lib qoldi, xom javob: %r", text[:300])
    return result


def plain_text(text: str) -> str:
    """HTML yuborib bo'lmasa: teglarsiz oddiy matn."""
    return html.unescape(re.sub(r"<[^>]*>", "", text))
