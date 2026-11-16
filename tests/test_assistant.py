"""Assistant: free-text question -> goal, skill, budget -> measured to-do list."""
import pytest

from soe.advisor.assistant import ask, explain_not_applied, parse_question
from soe.advisor.session import Session

SKILLS = ["Comet", "Lightning Bolt", "Spark", "Twister", "Whirling Slash"]


@pytest.mark.parametrize("q,goal,skill,budget", [
    ("dobra nie jestem w stanie oneshotować moba X, co mogę zrobić żeby bić więcej z lightning bolta za 3 div",
     "hit", "Lightning Bolt", 3.0),
    ("jak zwiekszyc dps comet", "dps", "Comet", None),
    ("ciągle mnie oneshotują bossy", "survive", None, None),
    ("ciagle umieram", "survive", None, None),
    ("brakuje mi many na sparku", "mana", "Spark", None),
    ("I can't one shot anything with twister", "hit", "Twister", None),
    ("co poprawic", "dps", None, None),
])
def test_parse(q, goal, skill, budget):
    p = parse_question(q, SKILLS)
    assert p["goal"] == goal and p["skill"] == skill and p["budget_divine"] == budget


def test_not_applied_reason_in_polish():
    assert "triggered" in explain_not_applied({"excluded_by": ["Triggered"], "missing": []})
    assert "czarem" in explain_not_applied({"excluded_by": [], "missing": ["Spell"]})


@pytest.fixture(scope="module")
def s(kb_path, spirit_walker_code):
    sess = Session(kb_path)
    sess.load(spirit_walker_code, "sw")
    return sess


def test_ask_quick(s):
    base = s.pob.summary()
    r = ask(s, "nie oneshotuję moba, jak bić mocniej whirling slash", deep=False)
    assert r["skill"] == "Whirling Slash" and r["goal"] == "hit" and r["explain"]
    assert r["now"]["average_hit"] > 0
    assert all({"title", "gain", "cost", "score"} <= set(st) for st in r["steps"])
    scores = [st["score"] for st in r["steps"]]
    assert scores == sorted(scores, reverse=True)
    assert s.pob.summary() == base  # the main skill is switched back after the analysis
