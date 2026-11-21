"""The web page's script must parse: one syntax error leaves the whole app blank."""
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[1] / "soe" / "web" / "static" / "index.html"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_page_script_parses(tmp_path):
    html = PAGE.read_text(encoding="utf-8")
    js = html[html.index("<script>") + len("<script>"):html.rindex("</script>")]
    f = tmp_path / "page.js"
    f.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
