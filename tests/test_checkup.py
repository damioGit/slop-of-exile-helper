"""Gap fixes from the first advisor test, respec ranking and the check-up."""
import pytest

from soe.advisor.checkup import join_item, run_checkup, split_item
from soe.advisor.session import Session


@pytest.fixture(scope="module")
def s(kb_path, spirit_walker_code):
    sess = Session(kb_path)
    sess.load(spirit_walker_code, "sw")
    return sess


def test_points_budget(s):
    p = s.pob.points()
    assert (p["used"], p["available"]) == (124, 123)  # PoB itself counts this character 1 over
    assert p["weapon_set_1"] == p["weapon_set_2"] == p["weapon_set_max"] == 24
    assert p["ascendancy_used"] == 8 and p["active_weapon_set"] == 2
    assert "note" in s.overview(with_all_skills=False)["passive_points"]


def test_enemy_resists_from_boss_preset(s):
    e = s.overview(with_all_skills=False)["enemy"]
    assert e["Fire"] == e["Cold"] == e["Lightning"] == 50


def test_spirit_and_requirements_in_summary(s):
    assert s.base["SpiritReserved"] == 230 and s.base["SpiritUnreserved"] == 2
    assert s.base["ReqDex"] == 157


def test_inactive_weapon_set_node_is_explained(s):
    r = s.whatif_passives(remove=["Stimulants"])
    assert r["changes"] == {}
    assert any("weapon set 1" in n for n in r["notes"])


def test_unmodelled_node_is_explained(s):
    r = s.whatif_passives(remove=["Chronomancy"])
    assert any("does not calculate" in n and "Slow" in n for n in r["notes"])


def test_supports_apply_flags(s):
    g = next(g for g in s.pob.groups() if "Twister" in g["skills"])
    assert all(x["applies"] for x in g["gems"])


def test_socket_limit_warning(s):
    g = next(g for g in s.pob.groups() if "Twister" in g["skills"])
    r = s.try_changes([{"op": "set_gem", "group": g["index"], "gem": 7, "name": "Deliberation"}])
    assert any("support sockets" in n for n in r["notes"])
    with pytest.raises(ValueError):
        s.try_changes([{"op": "set_gem", "group": 999, "gem": 1, "level": 1}])


def test_try_changes_reports_points(s):
    r = s.try_changes([{"op": "alloc_node", "node": "Stand and Deliver"}])
    used = r["passive_points"]["used"]
    assert used[1] > used[0]


def test_rank_respec(s):
    r = s.rank_respec("dps", limit=10)
    rows = r["cheapest_refunds"]
    assert rows and all(rows[i]["loss_per_point"] <= rows[i + 1]["loss_per_point"] for i in range(len(rows) - 1))
    assert len(r["inactive_weapon_set_nodes"]) == 24
    assert all(x["points_freed"] >= 1 for x in rows)


def test_split_join_item_roundtrip():
    raw = "Rarity: RARE\nX\nGold Ring\nImplicits: 1\n+10 to Str\n+20 to Life\n{desecrated}+5% res"
    head, imp, exp = split_item(raw)
    assert imp == ["+10 to Str"] and exp == ["+20 to Life", "{desecrated}+5% res"]
    assert join_item(head, imp, exp) == raw
    assert "Implicits: 0" in join_item(head, [], exp)


def test_checkup(s):
    r = run_checkup(s)
    ids = [f["id"] for f in r["findings"]]
    for expected in ("tree-conditional", "mana-main", "hit-physical", "gear-dead", "tree-inactive-set", "tree-unmodelled"):
        assert expected in ids
    scores = [f["score"] for f in r["findings"]]
    assert scores == sorted(scores, reverse=True)
    dead_mods = next(f for f in r["findings"] if f["id"] == "gear-dead")["data"]["mods"]
    assert any("Rarity" in m["mod"] for m in dead_mods)
    assert not any(m["mod"] == "Corrupted" for m in dead_mods)
    gems = next(f for f in r["findings"] if f["id"] == "gem-levels")["data"]["gems"]
    assert not any(g["gem"] in ("Primal Bounty", "Wild Protector", "Vivid Stampede") and g["group"] > 16 for g in gems)
    assert s.pob.summary() == s.base  # check-up never changes the build


def test_goals_reorder(s):
    surv = run_checkup(s, {"survive": 3, "damage": 0, "mana": 0, "ease": 0, "speed": 0}, deep=False)
    mana = run_checkup(s, {"survive": 0, "damage": 0, "mana": 3, "ease": 3, "speed": 0}, deep=False)
    pos = lambda r, i: [f["id"] for f in r["findings"]].index(i)
    assert pos(surv, "hit-physical") < pos(surv, "mana-main")
    assert pos(mana, "mana-main") < pos(mana, "hit-physical")


def test_conditional_passives_are_not_called_dead(s):
    r = run_checkup(s)
    by = {f["id"]: f for f in r["findings"]}
    cond = by["tree-conditional"]["data"]["nodes"]
    assert "Killer Instinct" in cond  # "while on Full Life": a condition, not a dead node
    dead = by.get("tree-dead", {"data": {"nodes": []}})["data"]["nodes"]
    assert "Duration" not in dead  # changes skill durations even though DPS/EHP stay the same
