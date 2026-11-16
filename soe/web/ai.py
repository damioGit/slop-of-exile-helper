"""AI mode of the web assistant: the player's question goes to Claude (Claude Code CLI, headless) with the
same soe tools the MCP server gives, and the player's current build.

The CLI uses the player's own Claude login; nothing here holds an API key. One job runs at a time.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD_FILE = ROOT / "data" / "user" / "ai_build.txt"

SYSTEM = """You answer a Path of Exile 2 player inside the Slop of Exile Helper web app.
The player only sees your final answer, never the tool results, so put every number they need in the answer.
Start with load_build using the file path given in the message (it is the build open in the app), then follow
CLAUDE.md: numbers only from tool calls, before -> after with %, what each gain depends on, trade-offs,
order by impact per cost. Look things up on poe2wiki.net / poe2db.tw when the tools cannot answer.
Answer in Polish, casual, concrete. Markdown: short headings, lists, small tables. No preamble."""

TOOLS = ["mcp__soe", "WebSearch", "WebFetch"]
NOT_LOGGED_IN = ("Claude nie jest zalogowany na tym komputerze. Raz otwórz terminal, uruchom:\n\n    \"{exe}\"\n\n"
                 "wpisz /login i zaloguj się swoim kontem Claude. Potem tryb AI zadziała.")
TOOL_PL = {
    "load_build": "wczytuję build", "build_overview": "przegląd buildu", "checkup": "szukam problemów",
    "ask": "asystent", "rank_passives": "liczę pasywy", "rank_respec": "respec", "optimize_supports": "supporty",
    "optimize_tree": "drzewko", "improvement_plan": "plan ulepszeń", "stat_weights": "wagi statów",
    "mod_upgrades": "mody na itemie", "ideal_item": "idealny item", "gear_audit": "przegląd gearu",
    "find_upgrade": "szukam na trade", "price_check": "ceny poe.ninja", "try_changes": "testuję zmianę",
    "whatif_item": "testuję item", "whatif_passives": "testuję pasywy", "try_unique": "testuję unikat",
    "rank_uniques": "ranking unikatów", "suggest_combos": "synergie", "get_item": "czytam item",
    "WebSearch": "szukam w sieci", "WebFetch": "czytam stronę", "ToolSearch": "dobieram narzędzia",
}


def find_claude() -> str | None:
    """Claude Code CLI: SOE_CLAUDE, then PATH, then the copy bundled with the Claude desktop app (newest)."""
    if os.environ.get("SOE_CLAUDE"):
        return os.environ["SOE_CLAUDE"]
    exe = shutil.which("claude")
    if exe:
        return exe
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "Claude-Data"
    found = sorted(root.glob("*/claude-code/*/*/claude.exe"), key=lambda p: p.stat().st_mtime, reverse=True) \
        if root.exists() else []
    return str(found[0]) if found else None


class Jobs:
    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def start(self, question: str, build_code: str, summary: dict, resume: str | None = None) -> dict:
        exe = find_claude()
        if not exe:
            raise RuntimeError("Nie znalazłem Claude Code na tym komputerze (zainstaluj Claude Code albo ustaw SOE_CLAUDE).")
        with self.lock:
            if any(j["status"] == "running" for j in self.jobs.values()):
                raise RuntimeError("AI już odpowiada na poprzednie pytanie, poczekaj chwilę.")
            job = {"id": uuid.uuid4().hex[:10], "status": "running", "steps": [], "answer": None, "error": None,
                   "session": None, "started": time.time(), "cost_usd": None}
            self.jobs[job["id"]] = job
        BUILD_FILE.parent.mkdir(parents=True, exist_ok=True)
        BUILD_FILE.write_text(build_code, encoding="utf-8")
        who = f"{summary.get('ascendancy') or summary.get('class')} lvl {summary.get('level')}, główny skill {summary.get('main_skill')}"
        prompt = (f"Build gracza ({who}) jest w pliku: {BUILD_FILE}\nWczytaj go: load_build(code=\"{BUILD_FILE}\").\n\n"
                  f"Pytanie gracza:\n{question}") if not resume else (
                  f"(Build w aplikacji: {who}; jeśli się zmienił, wczytaj ponownie {BUILD_FILE}.)\n\n{question}")
        cmd = [exe, "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--append-system-prompt", SYSTEM, "--mcp-config", str(ROOT / ".mcp.json"), "--strict-mcp-config",
               "--allowedTools", *TOOLS, "--disallowedTools", "Bash", "Edit", "Write", "NotebookEdit",
               "--max-turns", "40"]
        if resume:
            cmd += ["--resume", resume]
        threading.Thread(target=self._run, args=(job, cmd, exe), daemon=True).start()
        return self.view(job["id"])

    def _run(self, job: dict, cmd: list[str], exe: str):
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 encoding="utf-8", errors="replace", creationflags=flags)
            for line in p.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("session_id"):
                    job["session"] = ev["session_id"]
                if ev.get("type") == "assistant":
                    for c in (ev.get("message") or {}).get("content") or []:
                        if c.get("type") == "tool_use":
                            name = c.get("name", "").split("__")[-1]
                            job["steps"].append(TOOL_PL.get(name, name))
                elif ev.get("type") == "result":
                    job["cost_usd"] = ev.get("total_cost_usd")
                    text = ev.get("result") or ""
                    if ev.get("is_error"):
                        job["error"] = NOT_LOGGED_IN.format(exe=exe) if "login" in text.lower() else (text or "błąd AI")
                    else:
                        job["answer"] = text
            p.wait(timeout=30)
            if not job["answer"] and not job["error"]:
                err = (p.stderr.read() or "").strip()
                job["error"] = err[-800:] or f"AI zakończyło się bez odpowiedzi (kod {p.returncode})"
        except Exception as e:  # noqa: BLE001
            job["error"] = f"{type(e).__name__}: {e}"
        finally:
            job["status"] = "error" if job["error"] else "done"
            job["seconds"] = round(time.time() - job["started"])

    def view(self, job_id: str) -> dict:
        j = self.jobs.get(job_id)
        if not j:
            raise KeyError("nie ma takiego zadania AI")
        return {k: j[k] for k in ("id", "status", "steps", "answer", "error", "session", "cost_usd")} | {
            "seconds": j.get("seconds") or round(time.time() - j["started"])}


jobs = Jobs()
