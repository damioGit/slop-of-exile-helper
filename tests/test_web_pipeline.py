"""Web API (FastAPI TestClient) and the patch diff of the launch pipeline."""
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from soe.pipeline.diff import diff_kb, report_md


@pytest.fixture(scope="module")
def client(kb_path, spirit_walker_code):
    import soe.web.app as web
    from soe.advisor.session import Session

    web.session = Session(kb_path)
    web.session.pool_workers = 3
    c = TestClient(web.app, raise_server_exceptions=False)
    r = c.post("/api/load", json={"code": spirit_walker_code})
    assert r.status_code == 200 and r.json()["main_skill"] == "Twister"
    yield c
    web.session.close_pool()


def test_page_and_status(client):
    assert "Slop of" in client.get("/").text
    s = client.get("/api/status").json()
    assert s["loaded"] and s["kb"]["pob_version"].startswith("v")


def test_overview_checkup_and_items(client):
    o = client.get("/api/overview").json()
    assert o["summary"]["main_skill"] == "Twister" and o["passive_points"]["active_weapon_set"] == 2
    c = client.get("/api/checkup", params={"survive": 3}).json()
    assert c["findings"]
    up = client.get("/api/mod_upgrades", params={"slot": "Ring 2"}).json()
    assert up["upgrades"]
    u = client.get("/api/uniques", params={"slot": "Ring 2", "limit": 3}).json()
    assert len(u["ranking"]) == 3


def test_try_and_apply_and_reset(client):
    base = client.get("/api/status").json()["summary"]
    t = client.post("/api/try", json={"steps": [{"op": "set_config", "var": "enemyIsBoss", "value": "None"}]}).json()
    assert "CombinedDPS" in t["changes"]
    a = client.post("/api/apply", json={"steps": [{"op": "alloc_node", "node": "Stand and Deliver"}]}).json()
    assert a["build_code"] and a["changes"]["CombinedDPS"][2] > 0
    assert client.get("/api/status").json()["summary"]["CombinedDPS"] > base["CombinedDPS"]
    client.post("/api/reset", json={})
    assert client.get("/api/status").json()["summary"] == base


def test_errors_are_json(client):
    r = client.post("/api/try", json={"steps": [{"op": "bogus"}]})
    assert r.status_code == 400 and "bogus" in r.json()["error"]
    r = client.get("/api/item", params={"slot": "Nope"})
    assert r.status_code == 200 and r.json() is None


def test_kb_search_endpoint(client):
    r = client.get("/api/kb/search", params={"q": "headhunter"}).json()
    assert r[0]["name"] == "Headhunter"


def test_diff_kb(kb_path, tmp_path):
    new = tmp_path / "new.sqlite"
    shutil.copy(kb_path, new)
    con = sqlite3.connect(new)
    con.execute("UPDATE gems SET stats_text = '[\"Deals 1 to 2 Fire Damage\"]' WHERE name = 'Fireball'")
    con.execute("DELETE FROM uniques WHERE name = 'Headhunter'")
    con.execute("UPDATE meta SET value = 'v9.9.9' WHERE key = 'pob_version'")
    con.commit()
    con.close()
    d = diff_kb(kb_path, new)
    assert "Fireball" in d["gems"]["changed"]
    assert "Deals 1 to 2 Fire Damage" in d["gems"]["changed"]["Fireball"]["added"]
    assert d["uniques"]["removed"] == ["Headhunter"]
    assert d["counts"]["passives"] == {"added": 0, "removed": 0, "changed": 0}
    md = report_md(d)
    assert "v9.9.9" in md and "Fireball" in md and "Headhunter" in md
    assert diff_kb(kb_path, kb_path)["counts"]["gems"] == {"added": 0, "removed": 0, "changed": 0}
