import re

# javob tilini AI chaqirmasdan, bir zumda aniqlash (faqat "yuklanmoqda" xabari uchun)
_WORD_RE = re.compile(r"[a-zа-яёўқғҳ']+", re.IGNORECASE)
_UZ_CYR_LETTERS = set("ўқғҳЎҚҒҲ")
_UZ_CYR_WORDS = {"нима", "учун", "қандай", "салом", "ёрдам", "керак", "бор", "йўқ", "менга", "сизга", "билан", "қилиш"}
_UZ_LAT_WORDS = {
    "nima", "qanday", "qayerda", "kim", "bu", "va", "uchun", "men", "sen", "siz", "salom", "bilan", "bor",
    "yo'q", "necha", "nega", "kerak", "mumkin", "ham", "emas", "edi", "menga", "senga", "qilish", "qiling",
    "yordam", "rahmat", "iltimos", "haqida", "qaysi", "qancha", "bo'ladi", "qanaqa", "aytib", "ber",
}
_EN_WORDS = {
    "the", "is", "are", "what", "how", "why", "who", "can", "could", "please", "you", "i", "do", "does", "to",
    "of", "in", "for", "and", "with", "this", "that", "my", "me", "help", "hello", "hi", "tell", "explain", "write",
}


def detect_lang(text: str) -> str:
    """'uz' (lotin, standart), 'uz_cyr' (o'zbek kirill), 'ru' yoki 'en'."""
    text = text.replace("’", "'").replace("ʻ", "'").replace("ʼ", "'").replace("`", "'").replace("‘", "'")
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "uz"
    cyrillic = sum("Ѐ" <= c <= "ӿ" for c in letters)
    words = [w.lower() for w in _WORD_RE.findall(text)]
    if cyrillic > len(letters) / 2:
        if any(c in _UZ_CYR_LETTERS for c in text) or sum(w in _UZ_CYR_WORDS for w in words) >= 1:
            return "uz_cyr"
        return "ru"
    uz = sum(w in _UZ_LAT_WORDS for w in words) + len(re.findall(r"\b[ogOG]'", text))
    en = sum(w in _EN_WORDS for w in words)
    return "en" if en > uz else "uz"
