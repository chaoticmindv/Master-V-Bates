"""Manual agent-loop stress test with a fake arena.ai: 12 tool rounds and one 429.

Run from the repo root:
    .venv\\Scripts\\python tests\\manual_agent_stress.py

Then in the browser: pick "Stress Test Model" in the model dropdown, keep Agent mode,
and send any message. The fake arena asks for one file write per round, rate-limits
once after round 2, and finishes after round 12.
"""
import json
import shutil
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arena import contracts  # noqa: E402
from arena.api import ArenaClient  # noqa: E402
import arena.web.app as appmod  # noqa: E402

PORT = 8898
ROUNDS = 12


class FakeReply:
    def __init__(self, lines=(), status=200, text=""):
        self.status_code, self._lines, self._text = status, list(lines), text
        self.error = None

    def iter_text(self):
        yield from self._lines

    @property
    def text(self):
        return self._text


state = {"turns": 0, "limited": False}


def fake_send(client, path, body):
    if not state["limited"] and state["turns"] == 2:
        state["limited"] = True
        print("  [fake arena] 429: too many requests")
        return FakeReply(status=429, text=json.dumps({"error": "Too many requests"}))
    state["turns"] += 1
    n = state["turns"]
    if n <= ROUNDS:
        tool = (f'<tool name="write_file"><path>round-{n:02}.txt</path>'
                f'<content>round {n}</content></tool>')
        print(f"  [fake arena] round {n}: write round-{n:02}.txt")
        return FakeReply([f"a0:{json.dumps(tool)}\n"])
    print("  [fake arena] final answer")
    return FakeReply([f"a0:{json.dumps('Completed all 12 rounds after the simulated rate limit.')}\n"])


_orig_classify = contracts.classify_error


def _classify(status, text=""):
    err = _orig_classify(status, text)
    if err.get("code") == "rate_limit":
        err["wait"] = 10  # keep the manual demo quick (the real wait is 60s)
    return err


contracts.classify_error = _classify

work = Path(tempfile.mkdtemp(prefix="arena_agent_stress_"))
chats = work / "chats"
chats.mkdir(parents=True, exist_ok=True)
workspace = work / "workspace"

appmod.CHATS_DIR = chats
appmod._client = ArenaClient(cookie_str="arena-auth-prod-v1.0=manual-test")
appmod._get_me = lambda client: ({"email": "stress@localhost", "full_name": "Stress Test"}, None)
appmod._check_session = lambda client, force=False: ({"email": "stress@localhost"}, None)
appmod._me_cache.update(t=0.0, user={"email": "stress@localhost"}, err=None)
appmod._ui_mode = "agent"
appmod._ui_modality = "auto"
appmod._stop.clear()
appmod.load_config = lambda: {"permission_mode": "acceptEdits", "workspace_dir": str(workspace)}
appmod.save_config = lambda cfg: None
appmod.sync_models = lambda force=False: {}
appmod.get_models_for_modality = lambda models, api_mod: [{
    "model_id": "stress-model", "name": "Stress Test Model", "org": "demo",
    "capabilities": ["chat"], "rank": 1, "arena_score": 0,
}]
appmod._send = fake_send

print(f"\nStress test UI: http://127.0.0.1:{PORT}")
print(f"Workspace:      {workspace}")
print("1. Pick 'Stress Test Model' in the model dropdown (Agent mode is already selected).")
print("2. Send any message.")
print("Expected: a 429 notice after round 2, a ~15s wait, then rounds 3-12 and a final answer.")
print("Press Ctrl+C to stop.\n")

threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
try:
    appmod.app.run(host="127.0.0.1", port=PORT, threaded=True, use_reloader=False)
finally:
    shutil.rmtree(work, ignore_errors=True)
