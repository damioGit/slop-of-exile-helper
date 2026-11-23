"""Lists player-facing Polish text that is not inside a t("English", "Polish") pair (developer check for i18n).

Usage: python scripts/find_polish.py [files...]   (default: every .py under soe/)
A Python string literal is reported when it has Polish letters or typical Polish words and is not the second
argument of t(...). Comments and docstrings are skipped.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PL_CHARS = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
PL_WORDS = re.compile(r"\b(nie|jest|albo|dla|oraz|tylko|przy|bez|gdy|daje|robi|zmienia|brak|potem|wszystko|jeszcze|"
                      r"czy|jak|lub|ten|jeden|jedna|nowe|nowa|stare|baza|bazy|moda|modów|z|na|w|i|ze|ich|go|jej)\b")


def polish(s: str) -> bool:
    return bool(PL_CHARS.search(s) or len(PL_WORDS.findall(s)) >= 2)


def scan(path: Path) -> list[tuple[int, str]]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    ok: set[int] = set()  # ids of nodes that are the Polish half of t(...)
    docs: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) in ("t", "_t"):
            for arg in node.args[1:2]:
                for sub in ast.walk(arg):
                    ok.add(id(sub))
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
                docs.add(id(first.value))
    out = []
    for node in ast.walk(tree):
        if id(node) in ok or id(node) in docs:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and polish(node.value):
            out.append((node.lineno, node.value[:90]))
        elif isinstance(node, ast.JoinedStr):
            text = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
            if polish(text):
                out.append((node.lineno, text[:90]))
                for sub in ast.walk(node):
                    ok.add(id(sub))
    return sorted(set(out))


if __name__ == "__main__":
    files = [Path(a) for a in sys.argv[1:]] or sorted((ROOT / "soe").rglob("*.py"))
    total = 0
    for f in files:
        for line, text in scan(f):
            print(f"{f.relative_to(ROOT) if f.is_absolute() else f}:{line}: {text}")
            total += 1
    print(f"{total} found")
