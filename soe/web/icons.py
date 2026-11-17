"""Item and skill icons from poe2db.tw, cached on disk (data/icons) so each one is fetched once.

poe2db page /us/<Name_With_Underscores> (apostrophes dropped) shows the item art as the first
<img class=""> and, for gems, the skill icon as <img class="gemSkill">.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "data" / "icons"
INDEX = DIR / "index.json"
UA = "Mozilla/5.0 (Slop of Exile Helper; local build tool)"
_lock = threading.Lock()
_index: dict | None = None
_last_fetch = 0.0
MISS_RETRY = 7 * 86400  # a name without a page is asked again after a week (new league items)

_ITEM = re.compile(r'<img loading="lazy" class="" src="(https://cdn\.poe2db\.tw/image/[^"]+)"')
_SKILL = re.compile(r'<img loading="lazy" class="gemSkill" src="(https://cdn\.poe2db\.tw/image/[^"]+)"')


def _load() -> dict:
    global _index
    if _index is None:
        try:
            _index = json.loads(INDEX.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _index = {}
    return _index


def _save():
    DIR.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(_index, ensure_ascii=False), encoding="utf-8")


def page_name(name: str) -> str:
    return re.sub(r"\s+", "_", name.replace("'", "").replace("’", "").strip())


def _get(url: str) -> bytes:
    global _last_fetch
    wait = 0.4 - (time.time() - _last_fetch)  # be gentle with poe2db
    if wait > 0:
        time.sleep(wait)
    _last_fetch = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


def icon_file(name: str, kind: str = "item") -> Path | None:
    """Local path of the icon for an item / gem name (kind 'skill' = the round skill icon), or None."""
    key = f"{kind}:{name.lower()}"
    with _lock:
        idx = _load()
        hit = idx.get(key)
        if hit and hit.get("file") and (DIR / hit["file"]).exists():
            return DIR / hit["file"]
        if hit and not hit.get("file") and time.time() - hit.get("t", 0) < MISS_RETRY:
            return None
        url = None
        try:
            html = _get(f"https://poe2db.tw/us/{page_name(name)}").decode("utf-8", "replace")
            m = (_SKILL.search(html) if kind == "skill" else None) or _ITEM.search(html)
            url = m.group(1) if m else None
        except (urllib.error.URLError, OSError, TimeoutError):
            url = None
        if not url:
            idx[key] = {"file": None, "t": time.time()}
            _save()
            return None
        ext = Path(url).suffix or ".webp"
        fname = hashlib.sha1(url.encode()).hexdigest()[:16] + ext
        path = DIR / fname
        if not path.exists():
            try:
                data = _get(url)
            except (urllib.error.URLError, OSError, TimeoutError):
                return None
            DIR.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        idx[key] = {"file": fname, "url": url, "t": time.time()}
        _save()
        return path
