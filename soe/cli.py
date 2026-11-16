"""Command line entry point.

  soe eval <build code | path to .xml/.txt | ->   print build summary (or --full for every stat)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _read_build(arg: str) -> tuple[str, str]:
    """Returns ("code" | "xml", text)."""
    if arg == "-":
        text = sys.stdin.read()
    elif Path(arg).exists():
        text = Path(arg).read_text(encoding="utf-8")
    else:
        text = arg
    text = text.strip()
    if text.startswith("https://pobb.in/") or text.startswith("pobb.in/"):
        raise SystemExit("pobb.in links are not fetched yet; open the link, copy the code and paste it here")
    return ("xml", text) if text.startswith("<") else ("code", text)


def cmd_eval(args):
    from soe.engine.pob import PoB

    kind, text = _read_build(args.build)
    pob = PoB()
    pob.load_xml(text) if kind == "xml" else pob.load_code(text)
    data = pob.output() if args.full else pob.summary()
    print(json.dumps(data, indent=2, sort_keys=args.full, default=str))


def _out(obj):
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def cmd_kb(args):
    if args.kb_cmd == "build":
        from soe.kb.build import build

        _out(build())
        return
    from soe.kb import KB

    kb = KB()
    if args.kb_cmd == "search":
        sys.stdout.reconfigure(encoding="utf-8")
        for r in kb.search(" ".join(args.query), kind=args.kind, limit=args.limit):
            print(f"{r['kind']:<10} {r['name']:<40} {r['snippet']}")
    elif args.kb_cmd == "gem":
        _out(kb.gem(" ".join(args.name)))
    elif args.kb_cmd == "supports":
        _out([s["name"] for s in kb.supports_for(" ".join(args.name))])
    elif args.kb_cmd == "unique":
        _out(kb.unique(" ".join(args.name)))
    elif args.kb_cmd == "node":
        _out(kb.node(" ".join(args.name)))
    elif args.kb_cmd == "mods":
        rows = kb.mods(args.text, domain=args.domain, slot=args.slot, affix_type=args.type)
        _out([{k: r[k] for k in ("domain", "type", "affix", "text", "level", "grp")} for r in rows])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="soe", description="Slop of Exile Helper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("eval", help="calculate a build with PoB")
    e.add_argument("build", help="PoB build code, file with code/XML, or - for stdin")
    e.add_argument("--full", action="store_true", help="print every calculated stat")
    e.set_defaults(func=cmd_eval)

    k = sub.add_parser("kb", help="knowledge base: game data search")
    ks = k.add_subparsers(dest="kb_cmd", required=True)
    ks.add_parser("build", help="(re)build data/kb.sqlite from PoB")
    s = ks.add_parser("search", help="full-text search everything")
    s.add_argument("query", nargs="+")
    s.add_argument("--kind", choices=["gem", "skill", "mod", "base", "unique", "node", "ascendancy"])
    s.add_argument("--limit", type=int, default=20)
    for name, hlp in [("gem", "gem details"), ("supports", "supports that work with an active gem"),
                      ("unique", "unique item"), ("node", "passive node by name or id")]:
        ks.add_parser(name, help=hlp).add_argument("name", nargs="+")
    m = ks.add_parser("mods", help="item modifiers")
    m.add_argument("text", nargs="?", help="substring of the mod text")
    m.add_argument("--slot", help="weight key, e.g. ring, amulet, body_armour, str_armour, spear")
    m.add_argument("--type", help="Prefix / Suffix")
    m.add_argument("--domain", default="Item", help="Item, Jewel, Flask, Charm, Runes, Corruption, Desecrated, ...")
    k.set_defaults(func=cmd_kb)

    u = sub.add_parser("update", help="launch day: new PoB release -> engine check -> knowledge base -> patch report")
    u.add_argument("tag", nargs="?", help="PoB tag (default: latest release)")
    u.add_argument("--no-pin", action="store_true", help="do not write POB_VERSION")
    u.set_defaults(func=lambda a: _out(__import__("soe.pipeline.update", fromlist=["update"]).update(a.tag, not a.no_pin)))
    c = sub.add_parser("compare", help="patch report between two PoB versions (current setup untouched)")
    c.add_argument("old")
    c.add_argument("new")
    c.set_defaults(func=lambda a: _out(__import__("soe.pipeline.update", fromlist=["compare"]).compare(a.old, a.new)))

    w = sub.add_parser("web", help="local web app (http://127.0.0.1:8765)")
    w.add_argument("--port", type=int, default=8765)
    w.add_argument("--host", default="127.0.0.1")
    w.set_defaults(func=lambda a: __import__("soe.web.app", fromlist=["main"]).main(a.host, a.port))

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
