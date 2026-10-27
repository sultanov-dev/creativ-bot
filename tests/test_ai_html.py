"""utils/ai_html.py: model javobi ishonchsiz (prompt injection), shuning uchun allowlist sanitizer."""
import re

import pytest

from utils.ai_html import _safe_href, plain_text, sanitize_html


class TestAllowedTags:
    @pytest.mark.parametrize("tag", ["b", "i", "u", "s", "code", "pre"])
    def test_simple_tags_survive(self, tag):
        assert sanitize_html(f"<{tag}>x</{tag}>") == f"<{tag}>x</{tag}>"

    def test_uppercase_tags_are_lowercased(self):
        assert sanitize_html("<B>x</B>") == "<b>x</b>"

    def test_https_link_survives(self):
        out = sanitize_html('<a href="https://example.com/p?q=1&r=2">t</a>')
        assert out == '<a href="https://example.com/p?q=1&amp;r=2">t</a>'

    def test_single_quoted_href(self):
        assert sanitize_html("<a href='https://example.com'>t</a>") == '<a href="https://example.com">t</a>'

    def test_pre_code_nesting_is_allowed(self):
        assert sanitize_html("<pre><code>a</code></pre>") == "<pre><code>a</code></pre>"


class TestDangerousInput:
    @pytest.mark.parametrize(
        "href",
        [
            "javascript:alert(1)",
            "tg://user?id=1",
            "http://example.com",
            "ftp://example.com",
            "https://google.com@evil.com",
            "https://user:pw@example.com",
            "//example.com",
            "https://exa mple.com",
            "data:text/html;base64,AAAA",
            "",
        ],
    )
    def test_unsafe_href_drops_the_tag_but_keeps_text(self, href):
        out = sanitize_html(f'<a href="{href}">click</a>')
        assert "<a" not in out and "</a>" not in out
        assert "click" in out

    def test_link_without_href_is_dropped(self):
        assert sanitize_html("<a>click</a>") == "click"

    def test_entity_encoded_javascript_scheme_is_decoded_and_rejected(self):
        assert "<a" not in sanitize_html('<a href="java&#115;cript:alert(1)">x</a>')

    def test_unknown_tags_are_escaped(self):
        out = sanitize_html("<script>alert(1)</script>")
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_img_and_attributes_cannot_inject(self):
        out = sanitize_html('<img src=x onerror="alert(1)">')
        assert "<img" not in out

    def test_attributes_on_plain_tags_are_stripped(self):
        out = sanitize_html('<b onclick="x()">hi</b>')
        assert out == "<b>hi</b>"

    def test_quote_in_href_cannot_break_out_of_the_attribute(self):
        out = sanitize_html('<a href=\'https://e.com/"onmouseover="x\'>t</a>')
        assert out == '<a href="https://e.com/&quot;onmouseover=&quot;x">t</a>'
        assert out.count('"') == 2  # faqat atributning o'z qo'shtirnoqlari

    def test_nested_links_are_not_allowed(self):
        out = sanitize_html('<a href="https://a.com">x<a href="https://b.com">y</a></a>')
        assert out.count("<a ") == 1

    def test_ampersand_and_lt_are_escaped(self):
        assert sanitize_html("1 < 2 & 3 > 2") == "1 &lt; 2 &amp; 3 &gt; 2"

    def test_html_entities_are_not_double_decoded_into_tags(self):
        out = sanitize_html("&lt;script&gt;x&lt;/script&gt;")
        assert "<script>" not in out

    def test_tags_inside_code_are_not_interpreted(self):
        out = sanitize_html("<code><b>x</b></code>")
        assert out == "<code>x</code>"

    def test_link_inside_pre_is_dropped(self):
        out = sanitize_html('<pre><a href="https://a.com">x</a></pre>')
        assert "<a" not in out


class TestBalancing:
    def test_unclosed_tags_are_closed(self):
        assert sanitize_html("<b>bold <i>both") == "<b>bold <i>both</i></b>"

    def test_stray_closing_tag_is_ignored(self):
        assert sanitize_html("text</b> more") == "text more"

    def test_misnested_tags_are_repaired(self):
        out = sanitize_html("<b><i>x</b>y</i>")
        assert out.count("<b>") == out.count("</b>")
        assert out.count("<i>") == out.count("</i>")

    def test_empty_input(self):
        assert sanitize_html("") == ""

    def test_result_is_stripped(self):
        assert sanitize_html("  \n hi \n ") == "hi"


class TestEscapedTagRecovery:
    @pytest.mark.parametrize(
        "raw",
        ["&lt;b&gt;x&lt;/b&gt;", "&#60;b&#62;x&#60;/b&#62;", "&amp;lt;b&amp;gt;x&amp;lt;/b&amp;gt;", "\\u003cb\\u003ex\\u003c/b\\u003e"],
    )
    def test_model_escaped_allowed_tags_become_real_tags(self, raw):
        assert sanitize_html(raw) == "<b>x</b>"

    def test_escaped_disallowed_tag_stays_text(self):
        assert "<script" not in sanitize_html("&lt;script&gt;")


class TestDashes:
    def test_hyphen_inside_words_becomes_space(self):
        assert sanitize_html("so'z-so'z") == "so'z so'z"

    @pytest.mark.parametrize("dash", ["-", "–", "—", "‑"])
    def test_all_dash_kinds_removed_from_prose(self, dash):
        assert dash not in sanitize_html(f"a {dash} b")

    @pytest.mark.parametrize("marker", ["-", "*", "•", "–", "—"])
    def test_list_markers_become_bullets(self, marker):
        assert sanitize_html(f"{marker} bir\n{marker} ikki") == "• bir\n• ikki"

    def test_first_line_dash_after_tag_is_not_a_bullet(self):
        out = sanitize_html("<b>x</b>- y")
        assert "•" not in out and "-" not in out

    def test_urls_keep_their_hyphens(self):
        out = sanitize_html("qarang https://my-site.com/a-b yaxshi")
        assert "https://my-site.com/a-b" in out

    def test_code_keeps_dashes(self):
        assert sanitize_html("<code>--flag a-b</code>") == "<code>--flag a-b</code>"

    def test_negative_numbers_lose_the_sign_in_prose(self):
        # hujjatlashtirilgan xulq: model javobida tire butunlay yo'q qilinadi
        assert "-" not in sanitize_html("harorat -5 daraja")


class TestLeakedTags:
    def test_leaked_escaped_tag_is_logged_and_output_stays_safe(self, caplog):
        caplog.set_level("WARNING", logger="utils.ai_html")
        out = sanitize_html("matn &lt;b qoldi")
        assert "<b" not in out
        assert any("teg matn bo'lib qoldi" in r.message for r in caplog.records)

    def test_clean_answer_logs_nothing(self, caplog):
        caplog.set_level("WARNING", logger="utils.ai_html")
        sanitize_html("<b>salom</b>")
        assert not caplog.records


class TestSafeHref:
    def test_valid(self):
        assert _safe_href('href="https://example.com/x"') == "https://example.com/x"

    def test_missing(self):
        assert _safe_href("class='x'") is None

    def test_invalid_ipv6_does_not_raise(self):
        assert _safe_href('href="https://[::1"') is None

    def test_whitespace_is_stripped_but_inner_space_rejected(self):
        assert _safe_href('href="  https://example.com  "') == "https://example.com"
        assert _safe_href('href="https://exa mple.com"') is None


class TestPlainText:
    def test_strips_tags_and_unescapes(self):
        assert plain_text("<b>a &amp; b</b> &lt;c&gt;") == "a & b <c>"

    def test_empty(self):
        assert plain_text("") == ""


@pytest.mark.parametrize(
    "payload",
    [
        "<b>" * 500,
        "</b>" * 500,
        "<" * 1000,
        "&" * 1000,
        "<a href=\"https://a.com\">" * 200,
        "<pre><code>" * 100 + "x",
        "\n".join("- item" for _ in range(300)),
    ],
)
def test_pathological_inputs_do_not_crash_and_stay_balanced(payload):
    out = sanitize_html(payload)
    for tag in ("b", "i", "u", "s", "code", "pre", "a"):
        assert len(re.findall(rf"<{tag}[ >]", out)) == out.count(f"</{tag}>")
