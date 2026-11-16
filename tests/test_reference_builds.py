"""Real builds checked against numbers published on poe.ninja (which also calculates with PoB).

spirit_walker.txt: poe.ninja/poe2/builds/runesofaldur/character/RoucheS-5084/Vitya_MageBlood,
Runes of Aldur league, fetched 2026-11-16, PoB v0.23.1.
"""
from pathlib import Path

import pytest

from soe.engine.pob import PoB

BUILDS = Path(__file__).parent / "builds"


@pytest.fixture(scope="module")
def spirit_walker():
    pob = PoB()
    pob.load_code((BUILDS / "spirit_walker.txt").read_text(encoding="utf-8"))
    return pob.summary()


# value from poe.ninja, allowed relative error (ninja rounds e.g. 197k, 64k, 5.1k)
EXPECTED = {
    "Life": (1556, 0),
    "EnergyShield": (2649, 0),
    "Ward": (52, 0),
    "Mana": (714, 0),
    "Spirit": (232, 0),
    "Evasion": (22032, 0),
    "EvadeChance": (74, 0),
    "DeflectionRating": (19167, 0.001),
    "DeflectChance": (88, 0),
    "FireResist": (75, 0),
    "ColdResist": (75, 0),
    "LightningResist": (75, 0),
    "ChaosResist": (75, 0),
    "TotalEHP": (64_000, 0.01),
    "PhysicalMaximumHitTaken": (5_100, 0.01),
    "FireMaximumHitTaken": (17_000, 0.03),
    "ChaosMaximumHitTaken": (14_000, 0.03),
    "LifeRegenRecovery": (31, 0.02),
    "ManaRegenRecovery": (32, 0.03),
    "EnergyShieldRecharge": (331, 0.001),
    "MovementSpeedMod": (1.29, 0),
    "Str": (77, 0),
    "Dex": (176, 0),
    "Int": (125, 0),
    "TotalDPS": (197_000, 0.005),
    "Speed": (2.4, 0.02),
    "CritChance": (61, 0.01),
    "CritMultiplier": (5.22, 0),
}


def test_identity(spirit_walker):
    s = spirit_walker
    assert (s["class"], s["ascendancy"], s["level"], s["main_skill"]) == ("Huntress", "Spirit Walker", 100, "Twister")


@pytest.mark.parametrize("stat", EXPECTED)
def test_matches_poe_ninja(spirit_walker, stat):
    expected, rel = EXPECTED[stat]
    if rel == 0:  # ninja shows whole numbers (or 2 decimals for small multipliers)
        assert spirit_walker[stat] == pytest.approx(expected, abs=0.5 if expected >= 10 else 0.005)
    else:
        assert spirit_walker[stat] == pytest.approx(expected, rel=rel)
