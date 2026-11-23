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

from soe.i18n import lang, set_lang, t

ROOT = Path(__file__).resolve().parents[2]
BUILD_FILE = ROOT / "data" / "user" / "ai_build.txt"

SYSTEM = """You answer a Path of Exile 2 player inside the Slop of Exile Helper web app.
The player only sees your final answer, never the tool results, so put every number they need in the answer.
Start with load_build using the file path given in the message (it is the build open in the app), then follow
CLAUDE.md: numbers only from tool calls, before -> after with %, what each gain depends on, trade-offs,
order by impact per cost. Look things up on poe2wiki.net / poe2db.tw when the tools cannot answer.
Answer in {language}, casual, concrete. Markdown: short headings, lists, small tables. No preamble."""

TOOLS = ["mcp__soe", "WebSearch", "WebFetch"]
def not_logged_in(exe: str) -> str:
    return t(f"Claude is not logged in on this computer. Open a terminal once, run:\n\n    \"{exe}\"\n\n"
             "type /login and sign in with your Claude account. Then AI mode works.",
             f"Claude nie jest zalogowany na tym komputerze. Raz otwórz terminal, uruchom:\n\n    \"{exe}\"\n\n"
             "wpisz /login i zaloguj się swoim kontem Claude. Potem tryb AI zadziała.")


TOOL_LABELS = {  # tool -> (English, Polish) step label shown while the AI works
    "load_build": ("loading the build", "wczytuję build"), "build_overview": ("build overview", "przegląd buildu"),
    "checkup": ("looking for problems", "szukam problemów"), "ask": ("assistant", "asystent"),
    "rank_passives": ("ranking passives", "liczę pasywy"), "rank_respec": ("respec", "respec"),
    "optimize_supports": ("supports", "supporty"), "optimize_tree": ("tree", "drzewko"),
    "improvement_plan": ("improvement plan", "plan ulepszeń"), "stat_weights": ("stat weights", "wagi statów"),
    "mod_upgrades": ("mods on the item", "mody na itemie"), "ideal_item": ("ideal item", "idealny item"),
    "gear_audit": ("gear audit", "przegląd gearu"), "find_upgrade": ("searching trade", "szukam na trade"),
    "price_check": ("poe.ninja prices", "ceny poe.ninja"), "try_changes": ("testing a change", "testuję zmianę"),
    "whatif_item": ("testing an item", "testuję item"), "whatif_passives": ("testing passives", "testuję pasywy"),
    "try_unique": ("testing a unique", "testuję unikat"), "rank_uniques": ("ranking uniques", "ranking unikatów"),
    "suggest_combos": ("synergies", "synergie"), "get_item": ("reading an item", "czytam item"),
    "craft_routes": ("craft routes", "drogi craftu"), "craft_pool": ("mod pool", "pula modów"),
    "WebSearch": ("searching the web", "szukam w sieci"), "WebFetch": ("reading a page", "czytam stronę"),
    "ToolSearch": ("picking tools", "dobieram narzędzia"),
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
            raise RuntimeError(t("Claude Code not found on this computer (install Claude Code or set SOE_CLAUDE).",
                                 "Nie znalazłem Claude Code na tym komputerze (zainstaluj Claude Code albo ustaw SOE_CLAUDE)."))
        with self.lock:
            if any(j["status"] == "running" for j in self.jobs.values()):
                raise RuntimeError(t("The AI is still answering the previous question, wait a moment.",
                                     "AI już odpowiada na poprzednie pytanie, poczekaj chwilę."))
            job = {"id": uuid.uuid4().hex[:10], "status": "running", "steps": [], "answer": None, "error": None,
                   "session": None, "started": time.time(), "cost_usd": None, "lang": lang()}
            self.jobs[job["id"]] = job
        BUILD_FILE.parent.mkdir(parents=True, exist_ok=True)
        BUILD_FILE.write_text(build_code, encoding="utf-8")
        who = f"{summary.get('ascendancy') or summary.get('class')} level {summary.get('level')}, main skill {summary.get('main_skill')}"
        prompt = (f"The player's build ({who}) is in the file: {BUILD_FILE}\nLoad it: load_build(code=\"{BUILD_FILE}\").\n\n"
                  f"The player's question:\n{question}") if not resume else (
                  f"(Build in the app: {who}; if it changed, load {BUILD_FILE} again.)\n\n{question}")
        system = SYSTEM.format(language="Polish" if lang() == "pl" else "English")
        cmd = [exe, "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--append-system-prompt", system, "--mcp-config", str(ROOT / ".mcp.json"), "--strict-mcp-config",
               "--allowedTools", *TOOLS, "--disallowedTools", "Bash", "Edit", "Write", "NotebookEdit",
               "--max-turns", "40"]
        if resume:
            cmd += ["--resume", resume]
        threading.Thread(target=self._run, args=(job, cmd, exe), daemon=True).start()
        return self.view(job["id"])

    def _run(self, job: dict, cmd: list[str], exe: str):
        set_lang(job.get("lang"))  # this thread speaks the language of the page that asked
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
                            job["steps"].append(name)
                elif ev.get("type") == "result":
                    job["cost_usd"] = ev.get("total_cost_usd")
                    text = ev.get("result") or ""
                    if ev.get("is_error"):
                        job["error"] = not_logged_in(exe) if "login" in text.lower() else (text or t("AI error", "błąd AI"))
                    else:
                        job["answer"] = text
            p.wait(timeout=30)
            if not job["answer"] and not job["error"]:
                err = (p.stderr.read() or "").strip()
                job["error"] = err[-800:] or t(f"The AI finished without an answer (code {p.returncode})",
                                               f"AI zakończyło się bez odpowiedzi (kod {p.returncode})")
        except Exception as e:  # noqa: BLE001
            job["error"] = f"{type(e).__name__}: {e}"
        finally:
            job["status"] = "error" if job["error"] else "done"
            job["seconds"] = round(time.time() - job["started"])

    def view(self, job_id: str) -> dict:
        j = self.jobs.get(job_id)
        if not j:
            raise KeyError(t("no such AI job", "nie ma takiego zadania AI"))
        return {k: j[k] for k in ("id", "status", "answer", "error", "session", "cost_usd")} | {
            "steps": [t(*TOOL_LABELS[x]) if x in TOOL_LABELS else x for x in j["steps"]],
            "seconds": j.get("seconds") or round(time.time() - j["started"])}


jobs = Jobs()
