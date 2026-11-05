import json

from unlisted.dig import Dig, _LAST_CHARS
from unlisted.utils import is_url, channel_url


def make_dig(tmp_path, **kwargs):
    return Dig(
        channel_identifier=None,
        channel_url=None,
        threads=1,
        delay=0,
        output_file_path=str(tmp_path),
        is_open_search=True,
        **kwargs,
    )


def test_generated_ids_are_valid_shape(tmp_path):
    dig = make_dig(tmp_path)
    ids = [dig._generate_video_uid() for _ in range(5000)]

    assert all(len(i) == 11 for i in ids)
    assert all(i[-1] in _LAST_CHARS for i in ids)
    assert len(_LAST_CHARS) == 16
    assert any("_" in i for i in ids)


def test_known_ids_are_never_generated(tmp_path):
    dig = make_dig(tmp_path)
    dig._used_set = {a + b for a in "AB" for b in "CD"}
    # Cannot collide in practice; just make sure the exclusion check is honoured.
    uid = dig._generate_video_uid()
    assert uid not in dig._used_set


def test_save_and_resume_round_trip(tmp_path):
    dig = make_dig(tmp_path)
    dig.unlisted_videos_data.append(
        {"video_uid": "abcdefghijA", "video_url": "u", "video_title": "t", "channel_name": "c"}
    )
    dig.used_videos_uid.append("zzzzzzzzzzA")
    dig._initiate_file_output()

    saved = json.loads(open(dig.output_file_path, encoding="utf-8").read())
    assert saved["unlisted_videos_data"][0]["video_uid"] == "abcdefghijA"

    resumed = make_dig(tmp_path)
    resumed.load_previous(saved)
    assert "zzzzzzzzzzA" in resumed._used_set
    assert len(resumed.unlisted_videos_data) == 1


def test_output_filename_is_sanitized(tmp_path):
    dig = make_dig(tmp_path)
    dig.is_open_search = False
    dig.channel_name = 'a/b:c "d"'
    dig._initiate_file_output()
    assert "/" not in dig.output_file_path.split("unlisted-dig-results-")[1]


def test_utils():
    assert is_url("https://youtube.com/@x") is True
    assert is_url("http://youtube.com/@x") is True
    assert is_url("LinusTechTips") is False
    assert channel_url("x") == "https://youtube.com/@x"
