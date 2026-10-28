"""Anketa maydonlarini tekshirish va formatlash: handlers/anketa.py, utils/form_anketa.py, utils/num_matcher.py."""
import pytest

from handlers.anketa import _clean_name, _clean_phone, _is_skip
from states import Form
from tests.table import check, same
from texts import SKIP_BUTTON
from utils.form_anketa import PROFILE_FIELDS, format_anketa, full_name_of
from utils.num_matcher import extract_number
from utils.questions import QUESTIONS


def test_clean_name():
    check(_clean_name, [
        ("Aziz Karimov", "Aziz Karimov"),
        ("  Aziz    Karimov  ", "Aziz Karimov"),
        ("Aziz\nKarimov", "Aziz Karimov"),
        ("Sherzod O'ktamov", "Sherzod O'ktamov"),
        ("Азиз Каримов", "Азиз Каримов"),
        ("Aziz-Bek Karimov", "Aziz-Bek Karimov"),
        ("Aziz Karimov Ogli", "Aziz Karimov Ogli"),
        ("Ab Cd", "Ab Cd"),  # eng qisqa: 5 belgi
        ("A" * 39 + " " + "B" * 40, "A" * 39 + " " + "B" * 40),  # eng uzun: 80 belgi
    ])
    # bitta so'z, qisqa, raqam, harf yo'q, buyruq, 80 dan uzun
    same(_clean_name, [None, "", "   ", "Aziz", "A Bc", "Aziz Karimov2", "12345 67890", "!!!! ????", "/start now",
                       "A" * 41 + " " + "B" * 40], None)


def test_clean_phone():
    check(_clean_phone, [
        ("+998901234567", "+998901234567"),
        ("998901234567", "998901234567"),
        ("+998 90 123 45 67", "+998901234567"),
        ("(90) 123-45-67", "901234567"),
        ("  +998901234567  ", "+998901234567"),
        ("1234567", "1234567"),
        ("+" + "1" * 15, "+" + "1" * 15),
    ])
    # oxirgi ikkitasi: o'rtadagi "+" va ASCII bo'lmagan raqamlar
    same(_clean_phone, ["", "abc", "123456", "+123456", "1" * 16, "+" + "1" * 16, "90-abc-1234567", "++998901234567",
                        "99890123456a", "+998.90.123.45.67", "998+901234567", "٩٩٨٩٠١٢٣٤٥٦٧"], None)


def test_is_skip():
    same(_is_skip, [SKIP_BUTTON, SKIP_BUTTON.upper(), f"  {SKIP_BUTTON}  ", "/skip", "/SKIP"], True)
    same(_is_skip, [None, "", "skip", "o'tkazib yuborish", "/skip please"], False)


def test_extract_number():
    check(extract_number, [
        ("25", 25), ("men 25 yoshdaman", 25), ("25 yosh, 30 emas", 25), ("25.5", 25), ("yosh: 18!", 18), ("٢٥", 25),
        # "-25" -> 25: minus yo'qoladi (handler faqat 10..100 ni oladi, lekin "-25" aslida to'g'ri yosh emas)
        ("-25", 25),
        ("", None), ("yigirma besh", None), ("abc25", None), ("25abc", None), ("a1b", None), ("!!", None),
    ])


class TestFormatAnketa:
    BASE = {"full_name": "Aziz Karimov", "age": 25, "job": "Dasturchi", "about": "Salom", "join_group": "Qiziq"}

    def test_minimal_has_no_phone_or_username(self):
        out = format_anketa(self.BASE)
        assert "Aziz Karimov" in out and "25" in out and "Dasturchi" in out and out.endswith("\n")
        assert "Username" not in out and "Telefon" not in out
        assert "Telefon" not in format_anketa(self.BASE, with_phone=True)  # telefon bo'lmasa qator ham yo'q

    def test_username_is_never_shown(self):
        # username so'ralmaydi va anketada ko'rinmaydi (faqat bazada saqlanadi)
        assert "azizbek" not in format_anketa({**self.BASE, "username": "azizbek"}, with_phone=True)

    def test_phone_hidden_by_default_and_shown_for_admins(self):
        data = {**self.BASE, "phone": "+998901234567"}
        assert "+998901234567" not in format_anketa(data)
        assert "+998901234567" in format_anketa(data, with_phone=True)

    def test_html_in_every_text_field_is_escaped(self):
        evil = "<b>x</b>&"
        data = {"full_name": evil + " y", "username": "ab_cde", "phone": evil, "age": 20, "job": evil, "about": evil,
                "join_group": evil}
        out = format_anketa(data, with_phone=True)
        assert "<b>x</b>" not in out
        assert out.count("&lt;b&gt;x&lt;/b&gt;&amp;") >= 5

    def test_legacy_first_last_name(self):
        data = {k: v for k, v in self.BASE.items() if k != "full_name"} | {"first_name": "Aziz", "last_name": "Karimov"}
        assert "Aziz Karimov" in format_anketa(data)

    def test_missing_required_field_is_a_clear_keyerror(self):
        with pytest.raises(KeyError):
            format_anketa({k: v for k, v in self.BASE.items() if k != "job"})


def test_full_name_of():
    check(full_name_of, [
        ({"full_name": "A B", "first_name": "X", "last_name": "Y"}, "A B"),  # full_name ustun
        ({"first_name": "Aziz", "last_name": "Karimov"}, "Aziz Karimov"),
        ({"first_name": "Aziz", "last_name": None}, "Aziz"),
        ({"full_name": "", "first_name": "A"}, "A"),
        ({}, ""),
    ])


def test_profile_fields_cover_every_question():
    # username so'ralmaydi: Telegram'dan olinadi, lekin profilda saqlanadi
    questions = {s.rsplit(":", 1)[-1] for s in QUESTIONS if s}
    assert set(PROFILE_FIELDS) - {"username"} == questions
    assert all(hasattr(Form, f) for f in PROFILE_FIELDS if f != "username")
