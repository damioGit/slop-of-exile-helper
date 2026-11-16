"""poe.ninja price client on a fake offline cache (no network in tests)."""
import json

from soe.prices.ninja import Prices

CORE = {"items": [], "rates": {"exalted": 500.0, "chaos": 7.0}, "primary": "divine", "secondary": "chaos"}


def _write(cache, league, name, data):
    d = cache / league.replace(" ", "_")
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(data), encoding="utf-8")


def make(tmp_path):
    league = "Test League"
    _write(tmp_path, league, "exchange-Currency.json", {
        "core": CORE,
        "items": [{"id": "exalted", "name": "Exalted Orb"}, {"id": "chaos", "name": "Chaos Orb"}],
        "lines": [{"id": "exalted", "primaryValue": 0.002}, {"id": "chaos", "primaryValue": 0.1428}]})
    _write(tmp_path, league, "exchange-LineageSupportGems.json", {
        "core": CORE, "items": [{"id": "zi", "name": "Zerphi's Infamy"}], "lines": [{"id": "zi", "primaryValue": 1.5}]})
    _write(tmp_path, league, "stash-UniqueAccessories.json", {"core": CORE, "lines": [
        {"name": "Headhunter", "baseType": "Heavy Belt", "primaryValue": 60, "listingCount": 10, "corrupted": True},
        {"name": "Headhunter", "baseType": "Heavy Belt", "primaryValue": 50, "listingCount": 900, "corrupted": False},
        {"name": "Andvarius", "baseType": "Gold Ring", "primaryValue": 0.02, "listingCount": 4000}]})
    return Prices(league=league, offline=True, cache_dir=tmp_path)


def test_prices_from_cache(tmp_path):
    p = make(tmp_path)
    assert p.status()["league"] == "Test League" and p.rates["exalted"] == 500.0
    hh = p.price("headhunter")
    assert hh["divine"] == 50 and hh["text"] == "50.0 div" and not hh["corrupted"]
    assert p.price("Andvarius")["text"] == "10 ex"
    assert p.price("Zerphi's Infamy")["exalted"] == 750.0
    assert p.price("Exalted Orb")["text"] == "1 ex"
    assert p.price("Divine Orb")["divine"] == 1.0
    assert p.price("Not An Item") is None


def test_offline_without_cache(tmp_path):
    p = Prices(league="Nowhere", offline=True, cache_dir=tmp_path)
    assert p.price("Headhunter") is None
    assert p.fmt(None) == "?"


def test_safe_price_never_raises():
    from soe.prices import safe_price

    assert safe_price("Headhunter") is None  # empty offline cache in tests
    assert safe_price(None) is None
