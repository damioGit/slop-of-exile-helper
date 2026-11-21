"""Auto-updater status and the quick check-up cards (no network: conftest switches the updater off)."""
from soe.advisor import quick
from soe.pipeline import autoupdate


def test_status_shape_and_todo(monkeypatch):
    u = autoupdate.Updater()
    u.state = {"remote": {"checked": 1, "pob_latest": "v99.0.0", "app_behind": 2}}
    s = u.status()
    assert s["pob"]["update"] and s["pob"]["latest"] == "v99.0.0"
    assert any("v99.0.0" in t for t in s["todo"]) and any("appki" in t for t in s["todo"])
    assert not s["ok"] and s["updater"]["auto"] is False  # SOE_AUTOUPDATE=0 in tests
    assert u.maybe_start() is False  # switched off: nothing starts on its own


def test_run_swaps_engine_after_pob_update(monkeypatch):
    from soe.pipeline import update as up

    u = autoupdate.Updater()
    monkeypatch.setattr(u, "remote", lambda force=False: {"pob_latest": "v99.0.0"})
    monkeypatch.setattr(u, "_save", lambda: None)
    monkeypatch.setattr(up, "update", lambda tag: {"ok": True})
    monkeypatch.setattr(autoupdate.shutil, "which", lambda name: "git")
    from soe.kb import poe2db

    monkeypatch.setattr(poe2db, "sync", lambda kb, refresh=False, log=None: {"pages": 0, "ok": 0, "failed": []})
    called = []
    u.on_new_engine = lambda: called.append(1)
    u.run()
    assert called and "PoB" in u.state["last_result"]["done"][0] and not u.running


def test_quick_cards():
    b = {"FireResist": 75, "ColdResist": 60, "LightningResist": 75, "ChaosResist": -20,
         "Str": 50, "ReqStr": 80, "Dex": 10, "ReqDex": 0, "Int": 10, "ReqInt": 0,
         "SpiritUnreserved": -10, "Spirit": 100, "ManaPerSecondCost": 50, "ManaRegenRecovery": 20,
         "PhysicalMaximumHitTaken": 2000, "FireMaximumHitTaken": 9000}
    assert quick.resist_card(b)["level"] == "bad" and "Cold -15%" in quick.resist_card(b)["text"]
    assert quick.attribute_card(b)["level"] == "bad" and "Str 30" in quick.attribute_card(b)["text"]
    assert quick.spirit_card(b)["level"] == "bad"
    assert quick.mana_card(b)["level"] == "warn"
    assert quick.max_hit_card(b)["title"].endswith("Fizyczne")
