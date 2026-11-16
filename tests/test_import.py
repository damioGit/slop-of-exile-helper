"""Character import from poe.ninja, with poe.ninja replaced by fakes (no network in tests)."""
import io
import urllib.error

import pytest

import soe.prices.characters as ch
from soe.advisor.session import Session

STATE = {"snapshotVersions": [
    {"url": "forbiddenrites", "name": "Forbidden Rites", "version": "v1", "snapshotName": "forbidden-rites"},
    {"url": "runesofaldur", "name": "Runes of Aldur", "version": "v2", "snapshotName": "runes-of-aldur"},
    {"url": "runesofaldurhc", "name": "HC Runes of Aldur", "version": "v3", "snapshotName": "hc-runes-of-aldur"},
]}


def _http(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))


def fake_get(code_for, blocked=False):
    def _get(url, tries=3):
        if blocked:
            raise _http(403)
        if url.endswith("index-state"):
            return STATE
        for version, code in code_for.items():
            if f"/builds/{version}/character" in url:
                return {"account": "RoucheS-5084", "name": "Vitya_MageBlood", "league": "Runes of Aldur",
                        "class": "Spirit Walker", "level": 100, "pathOfBuildingExport": code,
                        "updatedUtc": "2026-06-27"}
        raise _http(404)
    return _get


def test_parse_ref():
    assert ch.parse_ref("https://poe.ninja/poe2/builds/runesofaldur/character/RoucheS-5084/Vitya_MageBlood?i=1") == \
        ("RoucheS-5084", "Vitya_MageBlood", "runesofaldur")
    assert ch.parse_ref("RoucheS#5084", "Vitya") == ("RoucheS-5084", "Vitya", None)
    assert ch.parse_ref("RoucheS#5084/Vitya") == ("RoucheS-5084", "Vitya", None)
    with pytest.raises(ValueError):
        ch.parse_ref("RoucheS#5084")


def test_fetch_finds_league(monkeypatch, tmp_path):
    monkeypatch.setattr(ch, "_get", fake_get({"v2": "CODE"}))
    monkeypatch.setattr("soe.prices.ninja.CACHE", tmp_path)
    c = ch.fetch_character("RoucheS#5084", "Vitya_MageBlood")
    assert c["code"] == "CODE" and c["league"] == "Runes of Aldur" and c["class"] == "Spirit Walker"


def test_not_found_and_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr("soe.prices.ninja.CACHE", tmp_path)
    monkeypatch.setattr(ch, "_get", fake_get({}))
    with pytest.raises(ValueError, match="not found"):
        ch.fetch_character("Nobody#0001", "Nothing")
    monkeypatch.setattr(ch, "_get", fake_get({}, blocked=True))
    with pytest.raises(ch.Blocked, match="refusing"):
        ch.fetch_character("Nobody#0001", "Nothing")


def test_session_import_and_resync(monkeypatch, kb_path, spirit_walker_code):
    calls = []

    def fake_fetch(ref, name=None):
        calls.append((ref, name))
        return {"account": "RoucheS-5084", "name": "Vitya_MageBlood", "league": "Runes of Aldur",
                "class": "Spirit Walker", "level": 100, "code": spirit_walker_code, "updated": "x",
                "source": "poe.ninja"}

    monkeypatch.setattr(ch, "fetch_character", fake_fetch)
    s = Session(kb_path)
    r = s.import_character("RoucheS#5084", "Vitya_MageBlood")
    assert r["summary"]["main_skill"] == "Twister" and s.source["account"] == "RoucheS-5084"
    s.resync()
    assert calls[-1] == ("RoucheS-5084", "Vitya_MageBlood")
    s.load(spirit_walker_code)  # pasting a code forgets the import source
    assert s.source is None
    with pytest.raises(RuntimeError):
        s.resync()
