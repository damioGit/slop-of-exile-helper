"""Bridge to the Path of Building (PoE2) calculation engine, run headless in LuaJIT via lupa."""
from __future__ import annotations

import base64
import json
import os
import time
import zlib
from contextlib import contextmanager
from pathlib import Path

from lupa import luajit21

ROOT = Path(__file__).resolve().parents[2]
POB_DIR = ROOT / "vendor" / "PathOfBuilding-PoE2"
LUA_DIR = Path(__file__).resolve().parent / "lua"

SUMMARY_KEYS = [
    "TotalDPS", "CombinedDPS", "FullDPS", "AverageHit", "Speed", "CritChance", "CritMultiplier",
    "Life", "EnergyShield", "Ward", "Mana", "Spirit", "Armour", "Evasion",
    "EvadeChance", "DeflectionRating", "DeflectChance",
    "FireResist", "ColdResist", "LightningResist", "ChaosResist",
    "TotalEHP", "PhysicalMaximumHitTaken", "FireMaximumHitTaken", "ColdMaximumHitTaken",
    "LightningMaximumHitTaken", "ChaosMaximumHitTaken",
    "LifeRegenRecovery", "ManaRegenRecovery", "EnergyShieldRecharge",
    "MovementSpeedMod", "Str", "Dex", "Int",
]


def decode_build_code(code: str) -> str:
    """pobb.in / PoB export code (url-safe base64 of zlib) -> build XML."""
    code = code.strip()
    raw = base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))
    return zlib.decompress(raw).decode("utf-8")


def encode_build_code(xml: str) -> str:
    return base64.urlsafe_b64encode(zlib.compress(xml.encode("utf-8"), 9)).decode("ascii")


def _lua_to_py(v):
    if hasattr(v, "items"):  # Lua table
        d = {k: _lua_to_py(x) for k, x in v.items()}
        if d and all(isinstance(k, int) for k in d):
            return [d[k] for k in sorted(d)]
        return d
    return v


class PoB:
    """One headless PoB instance. Not thread-safe; use one per process."""

    def __init__(self, pob_dir: Path = POB_DIR, quiet: bool = True):
        self.src = pob_dir / "src"
        if not (self.src / "HeadlessWrapper.lua").exists():
            raise FileNotFoundError(f"PoB not found at {pob_dir}; run scripts/fetch_pob.py")
        self.lua = luajit21.LuaRuntime(unpack_returned_tuples=True)
        g = self.lua.globals()
        g.SOE_RUNTIME_LUA = (pob_dir / "runtime" / "lua").as_posix()
        g.SOE_SHIM = LUA_DIR.as_posix()
        g.SOE_INFLATE_HEX = lambda h: zlib.decompress(bytes.fromhex(h)).hex()
        g.SOE_DEFLATE_HEX = lambda h: zlib.compress(bytes.fromhex(h)).hex()
        if quiet:
            self.lua.execute("print = function() end")
        self.g = g
        t = time.perf_counter()
        with self._cwd():
            self.lua.execute((LUA_DIR / "bootstrap.lua").read_text(encoding="utf-8"))
            self.lua.execute((LUA_DIR / "soe_api.lua").read_text(encoding="utf-8"))
        self.boot_seconds = time.perf_counter() - t
        self.api = g.soe

    @contextmanager
    def _cwd(self):
        prev = os.getcwd()
        os.chdir(self.src)  # PoB loads data relative to src/
        try:
            yield
        finally:
            os.chdir(prev)

    def _call(self, fn, *args):
        with self._cwd():
            return fn(*args)

    # ---- loading / saving ----------------------------------------------
    def new_build(self) -> None:
        self._call(self.g.newBuild)

    def load_xml(self, xml: str, name: str = "build") -> None:
        self._call(self.g.loadBuildFromXML, xml, name)

    def load_code(self, code: str, name: str = "build") -> None:
        self.load_xml(decode_build_code(code), name)

    def export_xml(self) -> str:
        return self._call(self.api.export_xml)

    def export_code(self) -> str:
        return encode_build_code(self.export_xml())

    # ---- mutations -------------------------------------------------------
    def set_class(self, cls: str, ascendancy: str | None = None) -> bool:
        return bool(self._call(self.api.set_class, cls, ascendancy))

    def set_level(self, level: int) -> None:
        self._call(self.api.set_level, level)

    def paste_gems(self, text: str) -> None:
        self._call(self.api.paste_gems, text)

    def add_item(self, raw: str):
        return self._call(self.api.add_item, raw)

    def alloc_node(self, node_id: int):
        return self._call(self.api.alloc_node, node_id)

    def dealloc_node(self, node_id: int) -> bool:
        return bool(self._call(self.api.dealloc_node, node_id))

    def reachable(self, node_type: str = "Notable", limit: int = 20) -> list[dict]:
        return _lua_to_py(self._call(self.api.reachable, node_type, limit)) or []

    def recalc(self) -> None:
        self._call(self.api.recalc)

    def node_path(self, node_id: int) -> list[int]:
        return _lua_to_py(self._call(self.api.node_path, node_id)) or []

    def node_info(self, node_id: int) -> dict | None:
        return _lua_to_py(self._call(self.api.node_info, node_id))

    # gems / skills
    def groups(self) -> list[dict]:
        """Socket groups with gems and the active skills they grant (1-based indexes, like PoB)."""
        return _lua_to_py(self._call(self.api.list_groups)) or []

    def set_gem(self, group: int, gem: int, **fields) -> bool:
        """Change name/level/quality/enabled of a gem; gem index past the end adds a new gem."""
        return bool(self._call(self.api.set_gem, group, gem, json.dumps(fields)))

    def remove_gem(self, group: int, gem: int) -> bool:
        return bool(self._call(self.api.remove_gem, group, gem))

    def set_main_skill(self, group: int, skill: int = 1) -> bool:
        return bool(self._call(self.api.set_main, group, skill))

    def all_skill_dps(self) -> list[dict]:
        """DPS of every active skill in every enabled group (main skill is restored)."""
        return _lua_to_py(self._call(self.api.all_skill_dps)) or []

    # items
    def items(self, active_only: bool = False) -> list[dict]:
        """Equipped items: slot, name, base, rarity, active (used by calcs) and raw text."""
        res = _lua_to_py(self._call(self.api.list_items)) or []
        return [i for i in res if i["active"]] if active_only else res

    def resolve_slot(self, slot: str) -> str:
        """'Weapon 1'/'Weapon 2' -> the slot of the weapon set the build actually uses."""
        if slot.startswith("Weapon") and not slot.endswith("Swap") and self._call(self.api.uses_second_weapon_set):
            return slot + " Swap"
        return slot

    def equip(self, slot: str, raw: str, exact_slot: bool = False):
        return self._call(self.api.equip, slot if exact_slot else self.resolve_slot(slot), raw)

    def unequip(self, slot: str, exact_slot: bool = False) -> bool:
        return bool(self._call(self.api.unequip, slot if exact_slot else self.resolve_slot(slot)))

    # config
    def config_options(self) -> list[dict]:
        return _lua_to_py(self._call(self.api.config_options)) or []

    def set_config(self, var: str, value) -> None:
        self._call(self.api.set_config, var, json.dumps(value))

    # ---- snapshot / rollback ----------------------------------------------
    def snapshot(self) -> str:
        return self.export_xml()

    def restore(self, snap: str) -> None:
        self.load_xml(snap)

    @contextmanager
    def trial(self):
        """Try changes and roll them back: `with pob.trial(): pob.set_gem(...); s = pob.summary()`."""
        snap = self.snapshot()
        try:
            yield self
        finally:
            self.restore(snap)

    # ---- what-if (fast, never changes the build) ----------------------------
    def whatif(self, *, add_nodes=None, with_path=False, remove_nodes=None, slot=None, item_raw=None,
               full: bool = False, exact_slot: bool = False) -> dict:
        """Calculate a hypothetical change with PoB's own calculator.

        add_nodes/remove_nodes: passive node ids (with_path=True also takes the shortest path).
        slot + item_raw: put that item in the slot; slot alone: empty the slot.
        'Weapon 1/2' maps to the active weapon set unless exact_slot=True.
        Returns the summary stats (or every stat with full=True) plus `points` spent.
        Stats the build no longer has (e.g. DPS with no weapon) are 0.
        """
        if slot and not exact_slot:
            slot = self.resolve_slot(slot)
        spec = {k: v for k, v in dict(add_nodes=add_nodes, with_path=with_path, remove_nodes=remove_nodes,
                                       slot=slot, item_raw=item_raw).items() if v}
        out = _lua_to_py(self._call(self.api.whatif, json.dumps(spec)))
        points = out.pop("__points", 0)
        res = out if full else {k: out.get(k, 0) for k in SUMMARY_KEYS}
        res["points"] = points
        return res

    # ---- results ---------------------------------------------------------
    @property
    def build(self):
        return self.g.build

    def output(self) -> dict:
        """Every scalar PoB shows in the sidebar / calcs tab for the main skill."""
        out = self.build.calcsTab.mainOutput
        return {k: v for k, v in out.items() if isinstance(v, (int, float, bool, str))}

    def summary(self) -> dict:
        b = self.build
        o = self.output()
        return {
            "class": b.spec.curClassName,
            "ascendancy": b.spec.curAscendClassName,
            "level": b.characterLevel,
            "main_skill": self._main_skill_name(),
            "passives_allocated": self._call(self.api.allocated_count),
            **{k: o.get(k, 0) for k in SUMMARY_KEYS},
        }

    def _main_skill_name(self):
        try:
            return self.build.calcsTab.mainEnv.player.mainSkill.activeEffect.grantedEffect.name
        except Exception:
            return None
