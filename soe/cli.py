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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="soe", description="Slop of Exile Helper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("eval", help="calculate a build with PoB")
    e.add_argument("build", help="PoB build code, file with code/XML, or - for stdin")
    e.add_argument("--full", action="store_true", help="print every calculated stat")
    e.set_defaults(func=cmd_eval)
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
