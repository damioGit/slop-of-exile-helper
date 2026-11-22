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


def test_full_update_refetches_everything(monkeypatch):
    from soe.kb import build as kb_build
    from soe.kb import craft_rules, poe2db

    u = autoupdate.Updater()
    u.state = {}  # not the real state file of this machine
    calls = {}
    monkeypatch.setattr(u, "_save", lambda: None)
    monkeypatch.setattr(u, "remote", lambda force=False: u.state.setdefault("remote", {"pob_latest": None, "app_behind": 3}))
    monkeypatch.setattr(u, "_pob_damaged", lambda: False)
    monkeypatch.setattr(kb_build, "build", lambda *a, **k: calls.setdefault("kb", True))
    monkeypatch.setattr(poe2db, "sync", lambda kb, refresh=False, log=None: calls.setdefault("poe2db", refresh) and
                        {"pages": 1, "ok": 1, "failed": []} or {"pages": 1, "ok": 1, "failed": []})
    monkeypatch.setattr(craft_rules, "check", lambda force=False, fetch=None: calls.setdefault("rules", force))
    monkeypatch.setattr(u, "update_app", lambda: calls.setdefault("app", True) and {"ok": True})
    engine = []
    u.on_new_engine = lambda: engine.append(1)
    u.run(force=True, full=True)
    assert calls == {"kb": True, "poe2db": True, "rules": True, "app": True}
    assert engine and u.restart_needed and not u.running
    assert any("appka" in d for d in u.state["last_result"]["done"])
