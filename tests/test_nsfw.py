"""utils/nsfw.py + handlers/ads.py: matnsiz kontent (rasm, stiker, video...) 18+ tekshiruvi — avval model, keyin AI."""
from typing import Any

import cv2
import numpy as np
import pytest
from aiogram.methods import DeleteMessage
from aiogram.types import Animation, Document, PhotoSize, Poll, PollOption, Sticker, Update

import database as dbm
import texts
from tests import telegram_fakes as tf
from tests.flow import feed
from utils import nsfw

G = tf.GROUP_ID
USER = 555


def _jpeg() -> bytes:
    ok, buf = cv2.imencode(".jpg", np.full((400, 400, 3), 128, np.uint8))
    return buf.tobytes()


class FakeDetector:
    def __init__(self) -> None:
        self.found: list[dict] = []
        self.calls = 0

    def detect(self, image) -> list[dict]:
        self.calls += 1
        return self.found


@pytest.fixture
def detector(monkeypatch) -> FakeDetector:
    fake = FakeDetector()
    monkeypatch.setattr(nsfw, "_detector", fake)
    monkeypatch.setattr(nsfw, "_detector_failed", False)
    return fake


@pytest.fixture
def downloads(monkeypatch) -> list[str]:
    fetched: list[str] = []

    async def fake(bot, file_id):
        fetched.append(file_id)
        return _jpeg()

    monkeypatch.setattr(nsfw, "_download", fake)
    return fetched


@pytest.fixture
def vision(monkeypatch):
    """AI_VISION yoqilgan, AI javobi `vision.answer`."""

    class Fake:
        answer = "OK"
        calls: list = []

        async def __call__(self, messages, **kw):
            self.calls.append(messages)
            return self.answer

    fake = Fake()
    fake.calls = []
    monkeypatch.setattr(nsfw, "AI_VISION", True)
    monkeypatch.setattr(nsfw, "ask_ai", fake)
    return fake


def deleted(session) -> list[int]:
    return [m.message_id for m in session.of(DeleteMessage)]


PHOTO = [PhotoSize(file_id="small", file_unique_id="u-photo-s", width=90, height=90),
         PhotoSize(file_id="mid", file_unique_id="u-photo", width=320, height=320)]


async def post(dp, bot, changes: dict[str, Any], *, user: int = USER, message_id: int = 800) -> None:
    msg = tf.group_message_obj(user, "x", message_id=message_id).model_copy(update={"text": None, **changes})
    await feed(dp, bot, Update.model_validate({"update_id": 70000 + message_id, "message": msg.model_dump(by_alias=True)}))


def sticker(unique="u-st", *, set_name="cats", animated=False) -> Sticker:
    thumb = PhotoSize(file_id="st-thumb", file_unique_id="u-st-thumb", width=128, height=128)
    return Sticker(file_id="st", file_unique_id=unique, type="regular", width=512, height=512, is_animated=animated,
                   is_video=False, set_name=set_name, thumbnail=thumb)


class TestLocalModel:
    async def test_exposed_body_is_deleted_without_ai_and_remembered(self, dp, bot, session, detector, downloads, vision):
        detector.found = [{"class": "MALE_GENITALIA_EXPOSED", "score": 0.8, "box": [0, 0, 1, 1]}]
        await post(dp, bot, {"photo": PHOTO})
        assert deleted(session) == [800] and downloads == ["mid"] and vision.calls == []
        assert texts.NSFW_NOTICE.format(name=f"U{USER}") in session.texts_to(G)
        assert await dbm.get_media_verdict("u-photo") == nsfw.NSFW
        await post(dp, bot, {"photo": PHOTO}, message_id=801)  # o'sha rasm qayta: yuklanmaydi
        assert deleted(session) == [800, 801] and downloads == ["mid"]

    async def test_clean_photo_stays_and_is_not_rechecked(self, dp, bot, session, detector, downloads):
        detector.found = [{"class": "FACE_MALE", "score": 0.9, "box": [0, 0, 1, 1]}]
        await post(dp, bot, {"photo": PHOTO})
        await post(dp, bot, {"photo": PHOTO}, message_id=801)
        assert deleted(session) == [] and downloads == ["mid"]

    async def test_unsure_without_ai_vision_stays_and_is_not_cached(self, dp, bot, session, detector, downloads):
        detector.found = [{"class": "FEMALE_BREAST_EXPOSED", "score": 0.3, "box": [0, 0, 1, 1]}]
        await post(dp, bot, {"photo": PHOTO})
        assert deleted(session) == [] and await dbm.get_media_verdict("u-photo") is None

    async def test_model_missing_and_no_ai_keeps_the_message(self, dp, bot, session, downloads, monkeypatch):
        monkeypatch.setattr(nsfw, "_detector", None)
        monkeypatch.setattr(nsfw, "_detector_failed", True)
        await post(dp, bot, {"photo": PHOTO})
        assert deleted(session) == []


class TestAiVision:
    async def test_unsure_goes_to_ai_with_the_image(self, dp, bot, session, detector, downloads, vision):
        detector.found = [{"class": "BUTTOCKS_EXPOSED", "score": 0.35, "box": [0, 0, 1, 1]}]
        vision.answer = "NSFW"
        await post(dp, bot, {"photo": PHOTO})
        assert deleted(session) == [800] and len(vision.calls) == 1
        parts = vision.calls[0][1]["content"]
        assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    async def test_clean_sticker_is_shown_to_ai_once(self, dp, bot, session, detector, downloads, vision):
        vision.answer = "NSFW"  # chizilgan rasm: model ko'rmadi, AI ko'rdi
        await post(dp, bot, {"sticker": sticker()})
        await post(dp, bot, {"sticker": sticker()}, message_id=801)
        assert deleted(session) == [800, 801] and len(vision.calls) == 1

    async def test_ai_failure_is_not_cached(self, dp, bot, session, detector, downloads, vision, monkeypatch):
        from utils.ai import AIError

        detector.found = [{"class": "BUTTOCKS_EXPOSED", "score": 0.35, "box": [0, 0, 1, 1]}]

        async def down(messages, **kw):
            raise AIError("503")

        monkeypatch.setattr(nsfw, "ask_ai", down)
        await post(dp, bot, {"photo": PHOTO})
        assert deleted(session) == [] and await dbm.get_media_verdict("u-photo") is None


class TestWhatIsChecked:
    async def test_adult_sticker_set_name_is_enough(self, dp, bot, session, detector, downloads):
        await post(dp, bot, {"sticker": sticker("u-x", set_name="hot_porn_pack")})
        assert deleted(session) == [800] and downloads == []

    async def test_animated_sticker_uses_its_thumbnail(self, detector):
        msg = tf.group_message_obj(USER, "x").model_copy(update={"sticker": sticker(animated=True)})
        ref = nsfw.media_of(msg)
        assert ref is not None and ref.file_id is None and ref.thumb_id == "st-thumb"

    def test_big_video_is_checked_by_its_cover_only(self):
        thumb = PhotoSize(file_id="cover", file_unique_id="u-cover", width=320, height=180)
        gif = Animation(file_id="gif", file_unique_id="u-gif", width=320, height=180, duration=3,
                        file_size=50 * 1024 * 1024, thumbnail=thumb)
        ref = nsfw.media_of(tf.group_message_obj(USER, "x").model_copy(update={"animation": gif}))
        assert ref is not None and ref.file_id is None and ref.thumb_id == "cover" and ref.video

    def test_image_sent_as_file_is_checked(self):
        doc = Document(file_id="d", file_unique_id="u-d", mime_type="image/png", file_size=1000)
        ref = nsfw.media_of(tf.group_message_obj(USER, "x").model_copy(update={"document": doc}))
        assert ref is not None and ref.file_id == "d" and not ref.video

    def test_video_frames_are_sampled(self, tmp_path):
        path = str(tmp_path / "v.mp4")
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 64))
        for _ in range(20):
            writer.write(np.full((64, 64, 3), 100, np.uint8))
        writer.release()
        frames = nsfw._decode_images(open(path, "rb").read(), video=True)
        assert 1 <= len(frames) <= nsfw.VIDEO_FRAMES

    async def test_poll_text_is_checked_for_ads(self, dp, bot, session, monkeypatch):
        poll = Poll(id="p", question="Kanalimizga obuna bo'ling t.me/spam", options=[
            PollOption(persistent_id="1", text="ha", voter_count=0), PollOption(persistent_id="2", text="yo'q", voter_count=0)],
            total_voter_count=0, is_closed=False, is_anonymous=True, type="regular", allows_multiple_answers=False,
            allows_revoting=False, members_only=False)
        await post(dp, bot, {"poll": poll})
        assert deleted(session) == [800]
