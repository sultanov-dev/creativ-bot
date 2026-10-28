"""Tezkor, mahalliy so'kinish filtri: AI'dan oldin ishlaydi (AI o'zbekcha so'kinishlarni o'tkazib yuborishi mumkin).

Matn normallashtiriladi (kirill -> lotin, leet: f*ck, bl@t, takroriy harflar) va so'zlar ro'yxat bilan solishtiriladi.
Ro'yxat ataylab ehtiyotkor: oddiy so'zlar (masalan, "sikl", "harom", "Nigeria") noto'g'ri belgilanmasligi kerak.
To'liq emas: qolganini AI tekshiradi.
"""
import re

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "j", "з": "z", "и": "i", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ў": "o", "қ": "q", "ғ": "g", "ҳ": "x",
}
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})
_INNER_MASK = re.compile(r"(?<=\w)[*._\-'`’ʻ‘](?=\w)")


def normalize(text: str) -> str:
    """Kichik harf, kirill -> lotin, h -> x, ichki maskalar (f*ck) olib tashlanadi, takroriy harflar bittaga."""
    text = text.lower()
    text = "".join(_CYR.get(ch, ch) for ch in text)
    text = _INNER_MASK.sub("", text)
    words = []
    for word in re.findall(r"[a-z0-9@$!]+", text):
        word = word.strip("@$!")  # gap oxiridagi/boshidagi tinish belgisi leet emas ("om!" -> "om")
        if not word:
            continue
        if re.search(r"[a-z]", word) and re.search(r"[0-9@$!]", word):
            word = word.translate(_LEET)  # faqat harf bilan aralash so'zlarda (25, 2024 o'zgarmaydi)
        words.append(re.sub(r"(.)\1+", r"\1", word.replace("h", "x")))
    return " ".join(words)


def _norm_list(items: str) -> tuple[str, ...]:
    return tuple(normalize(x) for x in items.split())


# so'zning istalgan joyida (aniq, noyob ildizlar)
_CONTAINS = _norm_list("fuck siktir blyad blyat bliad pizd pizdec zalup motherfucker")
# so'z shu bilan boshlansa
_PREFIX = _norm_list(
    "shit bitch asshole cunt whore bastard dickhead "
    "sikaman sikay sikib sikdir qotoq kotak jalab yeban yebat dalbayob dalbayop gandon gondon tashaq "
    "amingni omingni ammangni "
    "xuy xuev xuyn pidor pidar pidoras mudak mudil ebat ebal eban shlyux"
)
# faqat butun so'z
_EXACT = frozenset(_norm_list("suka suki suchka ska fck om"))


def _join_spelled(words: list[str]) -> list[str]:
    """"f u c k" kabi harflab yozilgan so'zni birlashtiradi (3 va undan ortiq bitta harf ketma-ket)."""
    out: list[str] = []
    run: list[str] = []
    for w in words + [""]:
        if len(w) == 1 and w.isalpha():
            run.append(w)
            continue
        if len(run) >= 3:
            out.append("".join(run))
        else:
            out.extend(run)
        run = []
        if w:
            out.append(w)
    return out


# 18+ mazmun (anketa uchun): ehtiyotkor ro'yxat, "seksiya" (sport seksiyasi), "Essex" kabi so'zlar tegmaydi
_ADULT_PREFIX = _norm_list("porn erotik erotic hentai intim prostitut fohisha minet xvideo xnxx xhamster onlyfans brazzers")
_ADULT_EXACT = frozenset(_norm_list("seks sex sexy seksi seksual seksualniy nude nudes nsfw eskort escort milf"))


def _words(text: str) -> list[str]:
    return _join_spelled(normalize(text or "").split())


def has_profanity(text: str) -> bool:
    for word in _words(text):
        if word in _EXACT or word.startswith(_PREFIX) or any(c in word for c in _CONTAINS):
            return True
    return False


def has_adult_content(text: str) -> bool:
    """18+ (jinsiy, porno) so'zlar: porno, seks, erotika... (kirill, maska va takroriy harflar bilan ham)."""
    return any(word in _ADULT_EXACT or word.startswith(_ADULT_PREFIX) for word in _words(text))
