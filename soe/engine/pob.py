"""Bridge to the Path of Building (PoE2) calculation engine, run headless in LuaJIT via lupa."""
from __future__ import annotations

import base64
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
    "Life", "EnergyShield", "Mana", "Spirit", "Armour", "Evasion",
    "FireResist", "ColdResist", "LightningResist", "ChaosResist",
    "TotalEHP", "Str", "Dex", "Int",
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
            **{k: o[k] for k in SUMMARY_KEYS if k in o},
        }

    def _main_skill_name(self):
        try:
            return self.build.calcsTab.mainEnv.player.mainSkill.activeEffect.grantedEffect.name
        except Exception:
            return None
