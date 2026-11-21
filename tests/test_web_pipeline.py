"""Web API (FastAPI TestClient) and the patch diff of the launch pipeline."""
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from soe.pipeline.diff import diff_kb, report_md


@pytest.fixture(scope="module")
def client(kb_path, spirit_walker_code, tmp_path_factory):
    import soe.web.app as web
    from soe.advisor.session import Session

    web.LAST = tmp_path_factory.mktemp("user") / "last_session.json"  # never the player's own file
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


def test_equipment_and_gear_endpoints(client):
    eq = client.get("/api/equipment").json()
    ring = next(i for i in eq["items"] if i["slot"] == "Ring 2")
    assert any("fractured" in m["flags"] for m in ring["mods"])
    a = client.get("/api/item_analysis", params={"slot": "Ring 2"}).json()
    assert "crafting" in a and a["mods"]
    g = client.get("/api/gear_audit").json()
    assert g["slots"] and g["level"]


def test_craft_endpoints(client):
    b = client.get("/api/craft/bases", params={"type": "Ring"}).json()
    assert "Ring" in b["types"] and any(x["name"] == "Gold Ring" for x in b["bases"])
    p = client.get("/api/craft/pool", params={"base": "Gold Ring", "ilvl": 82}).json()
    life = next(f for f in p["families"] if "to maximum Life" in f["text"])
    r = client.post("/api/craft/routes", json={"base": "Gold Ring", "ilvl": 82, "sims": 200,
                                                "wanted": [{"group": life["group"], "type": life["type"]}]}).json()
    assert r["possible"] and r["routes"]


def test_skill_groups_have_game_text(client):
    sg = client.get("/api/skill_groups").json()["groups"]
    gems = [g for grp in sg for g in grp["gems"]]
    twister = next(g for g in gems if g["name"] == "Twister")
    assert twister["description"] and twister["stats"] and twister["req"].get("dex")
    assert any(grp["main"] for grp in sg)


def test_ai_cli_override(monkeypatch):
    from soe.web import ai

    monkeypatch.setenv("SOE_CLAUDE", "C:/nope/claude.exe")
    assert ai.find_claude() == "C:/nope/claude.exe"


def test_build_id_and_restore_after_restart(client):
    import soe.web.app as web
    from soe.advisor.session import Session

    s = client.get("/api/status")
    bid = s.json()["build_id"]
    assert bid and s.headers["X-SOE-Build"] == bid
    assert client.post("/api/main_skill", json={"group": 1, "skill": 1}).status_code == 200
    assert web.LAST.exists()
    applied = web.session.base["main_skill"]
    old = web.session
    try:  # a restart loads the same build back, with the changes the player applied
        web.session = Session(old._kb_path)
        web._restore_last()
        assert web.session.loaded and web.session.base["main_skill"] == applied
        assert web.session.build_id != bid  # a new id: open pages refresh instead of mixing results
    finally:
        web.session = old


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


def test_quick_and_forge_build_endpoints(client):
    r = client.get("/api/quick").json()
    assert r["cards"] and {c["id"] for c in r["cards"]} >= {"res", "attr", "gear"}
    t = client.get("/api/craft/for_slot", params={"slot": "Ring 1"}).json()
    assert t["base"] and t["wanted"]
    v = client.post("/api/craft/value", json={"base": t["base"], "ilvl": t["item_level"], "slot": "Ring 1",
                                               "wanted": t["wanted"]}).json()
    assert v["slot"] == "Ring 1" and "dps_pct" in v
    s = client.get("/api/data_status").json()
    assert "pob" in s and "todo" in s
