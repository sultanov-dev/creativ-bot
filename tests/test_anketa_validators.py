"""Anketa maydonlarini tekshirish va formatlash: handlers/anketa.py, utils/form_anketa.py, utils/num_matcher.py."""
import pytest

from handlers.anketa import _clean_name, _clean_phone, _is_skip
from texts import SKIP_BUTTON
from utils.form_anketa import PROFILE_FIELDS, format_anketa, full_name_of
from utils.num_matcher import extract_number


class TestCleanName:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Aziz Karimov", "Aziz Karimov"),
            ("  Aziz    Karimov  ", "Aziz Karimov"),
            ("Aziz\nKarimov", "Aziz Karimov"),
            ("Li Yu", "Li Yu"),
            ("Sherzod O'ktamov", "Sherzod O'ktamov"),
            ("Азиз Каримов", "Азиз Каримов"),
            ("Aziz Karimov Ogli", "Aziz Karimov Ogli"),
            ("Aziz-Bek Karimov", "Aziz-Bek Karimov"),
        ],
    )
    def test_valid(self, raw, expected):
        assert _clean_name(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "   ",
            "Aziz",  # bitta so'z
            "A B",  # juda qisqa
            "Aziz Karimov2",  # raqam
            "12345 67890",
            "!!!! ????",  # harf yo'q
            "/start now",  # buyruq
            "A" * 41 + " " + "B" * 40,  # 80 belgidan uzun
        ],
    )
    def test_invalid(self, raw):
        assert _clean_name(raw) is None

    def test_exactly_80_chars_is_ok(self):
        name = "A" * 39 + " " + "B" * 40
        assert len(name) == 80 and _clean_name(name) == name

    def test_exactly_5_chars_is_ok(self):
        assert _clean_name("Ab Cd") == "Ab Cd"

    def test_four_chars_rejected(self):
        assert _clean_name("A Bc") is None


class TestPhone:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("+998901234567", "+998901234567"),
            ("998901234567", "998901234567"),
            ("+998 90 123 45 67", "+998901234567"),
            ("(90) 123-45-67", "901234567"),
            ("  +998901234567  ", "+998901234567"),
            ("1234567", "1234567"),
            ("+" + "1" * 15, "+" + "1" * 15),
        ],
    )
    def test_valid(self, raw, expected):
        assert _clean_phone(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        ["", "abc", "123456", "+123456", "1" * 16, "+" + "1" * 16, "90-abc-1234567", "++998901234567", "99890123456a",
         "+998.90.123.45.67"],
    )
    def test_invalid(self, raw):
        assert _clean_phone(raw) is None

    def test_non_ascii_digits_are_rejected(self):
        assert _clean_phone("٩٩٨٩٠١٢٣٤٥٦٧") is None

    def test_plus_in_the_middle_is_rejected(self):
        assert _clean_phone("998+901234567") is None


class TestSkip:
    @pytest.mark.parametrize("raw", [SKIP_BUTTON, SKIP_BUTTON.upper(), f"  {SKIP_BUTTON}  ", "/skip", "/SKIP"])
    def test_skip_variants(self, raw):
        assert _is_skip(raw)

    @pytest.mark.parametrize("raw", [None, "", "skip", "o'tkazib yuborish", "/skip please"])
    def test_not_skip(self, raw):
        assert not _is_skip(raw)


class TestExtractNumber:
    @pytest.mark.parametrize(
        "raw,expected",
        [("25", 25), ("men 25 yoshdaman", 25), ("25 yosh, 30 emas", 25), ("25.5", 25), ("yosh: 18!", 18),
         ("٢٥", 25)],
    )
    def test_extracts_first_whole_number(self, raw, expected):
        assert extract_number(raw) == expected

    @pytest.mark.parametrize("raw", ["", "yigirma besh", "abc25", "25abc", "a1b", "!!"])
    def test_none_when_no_standalone_number(self, raw):
        assert extract_number(raw) is None

    def test_negative_sign_is_lost(self):
        # "-25" -> 25: manfiy yosh qabul qilinib qolmasligi uchun handler faqat 10..100 ni oladi,
        # lekin "-25" aslida to'g'ri yosh emas
        assert extract_number("-25") == 25


class TestFormatAnketa:
    BASE = {"full_name": "Aziz Karimov", "age": 25, "job": "Dasturchi", "about": "Salom", "join_group": "Qiziq"}

    def test_minimal(self):
        out = format_anketa(self.BASE)
        assert "Aziz Karimov" in out and "25" in out and "Dasturchi" in out
        assert out.endswith("\n")
        assert "Username" not in out and "Telefon" not in out

    def test_username_is_never_shown(self):
        # username so'ralmaydi va anketada ko'rinmaydi (faqat bazada saqlanadi)
        assert "azizbek" not in format_anketa({**self.BASE, "username": "azizbek"}, with_phone=True)

    def test_phone_hidden_by_default_and_shown_for_admins(self):
        data = {**self.BASE, "phone": "+998901234567"}
        assert "+998901234567" not in format_anketa(data)
        assert "+998901234567" in format_anketa(data, with_phone=True)

    def test_phone_flag_without_phone(self):
        assert "Telefon" not in format_anketa(self.BASE, with_phone=True)

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
        data = {k: v for k, v in self.BASE.items() if k != "job"}
        with pytest.raises(KeyError):
            format_anketa(data)


class TestFullNameOf:
    def test_prefers_full_name(self):
        assert full_name_of({"full_name": "A B", "first_name": "X", "last_name": "Y"}) == "A B"

    def test_legacy_parts(self):
        assert full_name_of({"first_name": "Aziz", "last_name": "Karimov"}) == "Aziz Karimov"

    def test_only_first_name(self):
        assert full_name_of({"first_name": "Aziz", "last_name": None}) == "Aziz"

    def test_empty(self):
        assert full_name_of({}) == ""

    def test_empty_full_name_falls_back(self):
        assert full_name_of({"full_name": "", "first_name": "A"}) == "A"


def test_profile_fields_cover_every_question():
    from utils.questions import QUESTIONS
    from states import Form

    # username so'ralmaydi: Telegram'dan olinadi, lekin profilda saqlanadi
    assert set(PROFILE_FIELDS) - {"username"} == {s.rsplit(":", 1)[-1] for s in QUESTIONS}
    assert all(hasattr(Form, f) for f in PROFILE_FIELDS if f != "username")
