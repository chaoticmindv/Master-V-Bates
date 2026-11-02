"""Unit, edge-case and route tests for the desktop core: contracts, permissions,
agent tools, workspace mirroring, engine stream ordering and the Flask API."""

import base64
import json
import queue
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arena import accounts, agent, contracts, permissions, workspace  # noqa: E402
from arena.api import generate_uuidv7  # noqa: E402
from arena.auth import parse_cookie_input  # noqa: E402
from arena.engine import BrowserEngine, EngineResponse  # noqa: E402

KEY = "6LeTGMcsAAAAALuIlkVwIxaAuZA8VledA6d3Nnb0"


def counter():
    it = iter(range(1000))
    return lambda: f"id-{next(it)}"


# ---------- contracts.build_chat ----------

def test_battle_new_omits_model_a_and_has_b_message():
    path, body = contracts.build_chat(eval_id="E", new=True, mode="battle", modality="chat", content="hi", ids=counter())
    assert path == contracts.PATHS["create"]
    assert body["mode"] == "battle" and body["id"] == "E"
    assert "modelAId" not in body and "modelBMessageId" in body
    assert body["recaptchaV3Token"] is None and "recaptchaV2Token" not in body
    assert body["userMessage"]["content"] == "hi"


def test_direct_new_uses_direct_battle_with_one_model():
    _, body = contracts.build_chat(eval_id="E", new=True, mode="direct-battle", modality="webdev", content="x",
                                   ids=counter(), model_a="M")
    assert body["modelAId"] == "M" and body["mode"] == "direct-battle" and body["modality"] == "webdev"
    assert "modelBMessageId" not in body and "modelBId" not in body


def test_side_by_side_needs_both_models():
    with pytest.raises(ValueError):
        contracts.build_chat(eval_id="E", new=True, mode="side-by-side", modality="chat", content="x", ids=counter(), model_a="A")
    _, body = contracts.build_chat(eval_id="E", new=True, mode="side-by-side", modality="chat", content="x",
                                   ids=counter(), model_a="A", model_b="B")
    assert body["modelAId"] == "A" and body["modelBId"] == "B" and "modelBMessageId" in body


def test_direct_without_model_is_rejected():
    with pytest.raises(ValueError):
        contracts.build_chat(eval_id="E", new=True, mode="direct-battle", modality="chat", content="x", ids=counter())


def test_follow_up_posts_to_eval_without_mode():
    path, body = contracts.build_chat(eval_id="E1", new=False, mode="battle", modality="chat", content="x", ids=counter())
    assert path == contracts.PATHS["post"].format(eval_id="E1")
    assert "mode" not in body


def test_v2_token_replaces_v3():
    _, body = contracts.build_chat(eval_id="E", new=True, mode="battle", modality="chat", content="x", ids=counter(), v2_token="T")
    assert body["recaptchaV2Token"] == "T" and "recaptchaV3Token" not in body


def test_message_ids_sort_after_eval_id():
    eval_id = generate_uuidv7()
    _, body = contracts.build_chat(eval_id=eval_id, new=True, mode="battle", modality="chat", content="x", ids=generate_uuidv7)
    assert eval_id < body["userMessageId"] < body["modelAMessageId"] < body["modelBMessageId"]


def test_ui_maps():
    assert contracts.api_mode("agent") == "direct-battle" and contracts.api_mode("direct") == "direct-battle"
    assert contracts.api_mode("battle") == "battle"
    assert contracts.api_modality("code") == "webdev" and contracts.api_modality("auto") == "chat"
    assert contracts.api_modality("video") == "video"
    with pytest.raises(ValueError):
        contracts.api_mode("nope")
    with pytest.raises(ValueError):
        contracts.api_modality("nope")


# ---------- stream parsing and errors ----------

def test_parse_line_lanes_and_fallbacks():
    assert contracts.parse_line('a0:"hi"') == ("a", "text", "hi")
    assert contracts.parse_line('b0:"yo"') == ("b", "text", "yo")
    assert contracts.parse_line('0:"x"') == ("a", "text", "x")
    lane, kind, val = contracts.parse_line('b2:[{"type":"webdev"}]')
    assert (lane, kind) == ("b", "data") and val[0]["type"] == "webdev"
    assert contracts.parse_line("ag:not json") == ("a", "reasoning", "not json")
    for junk in ("", "garbage", "zz:1", "a"):
        assert contracts.parse_line(junk) is None


def test_line_splitter_handles_split_chunks():
    s = contracts.LineSplitter()
    assert s.feed('a0:"h') == []
    assert s.feed('i"\nb0') == ['a0:"hi"']
    assert s.flush() == ["b0"]
    assert s.flush() == []


@pytest.mark.parametrize("status,text,code", [
    (0, "boom", "network"),
    (403, '{"error":"recaptcha validation failed"}', "challenge"),
    (403, "<title>Just a moment...</title>", "cloudflare"),
    (401, "", "auth"),
    (429, "", "rate_limit"),
    (403, '{"error":"recaptcha rejected: too many requests"}', "rate_limit"),
    (400, '{"error":"Cannot pass model for battle mode"}', "bad_request"),
    (404, "", "eval_gone"),
    (500, "", "server"),
    (403, "nope", "forbidden"),
])
def test_classify_error(status, text, code):
    err = contracts.classify_error(status, text)
    assert err["code"] == code and err["message"]


def test_rate_limit_suggests_wait():
    assert contracts.classify_error(429, "")["wait"] >= 30


def test_discover_site_keys():
    html = f'<script src="https://www.google.com/recaptcha/enterprise.js?render={KEY}"></script>'
    assert contracts.discover_site_keys(html) == {"v3": KEY}
    assert contracts.discover_site_keys("<html></html>") == {}
    assert contracts.discover_site_keys(None) == {}


def test_load_overrides_validates(tmp_path, monkeypatch):
    monkeypatch.setattr(contracts, "PATHS", dict(contracts.PATHS))
    monkeypatch.setattr(contracts, "KEYS", dict(contracts.KEYS))
    f = tmp_path / "contracts.json"
    f.write_text(json.dumps({"paths": {"me": "/api/me2", "bad": "http://evil"}, "v3_key": "short", "v2_key": KEY}))
    changed = contracts.load_overrides(f)
    assert sorted(changed) == ["paths.me", "v2_key"]
    assert contracts.PATHS["me"] == "/api/me2" and "bad" not in contracts.PATHS
    assert contracts.load_overrides(tmp_path / "missing.json") == []
    (tmp_path / "list.json").write_text("[1,2]")
    assert contracts.load_overrides(tmp_path / "list.json") == []


def test_media_and_preview_discovery():
    media = contracts.find_media({"a": ["https://x.test/a.PNG?x=1", {"mimeType": "video/mp4", "url": "https://x.test/v"}]})
    assert {"url": "https://x.test/a.PNG?x=1", "kind": "image"} in media
    assert {"url": "https://x.test/v", "kind": "video"} in media
    assert contracts.find_media("https://x.test/song.mp3") == [{"url": "https://x.test/song.mp3", "kind": "audio"}]
    assert contracts.find_media({"url": "javascript:alert(1)"}) == []
    assert contracts.find_preview_url({"x": [{"previewUrl": "https://p.test"}]}) == "https://p.test"
    assert contracts.find_preview_url({"previewUrl": "ftp://no"}) is None
    assert contracts.webdev_items({"type": "webdev"}) == [{"type": "webdev"}]
    assert contracts.webdev_items([{"type": "x"}, 3, {"type": "webdev", "event": "init"}]) == [{"type": "webdev", "event": "init"}]


# ---------- permissions ----------

@pytest.mark.parametrize("mode,tool,inside,cmd,want", [
    ("default", "read_file", True, "", "allow"),
    ("default", "read_file", False, "", "ask"),
    ("bypassPermissions", "read_file", False, "", "allow"),
    ("plan", "read_file", True, "", "allow"),
    ("plan", "write_file", True, "", "deny"),
    ("plan", "run_cmd", True, "dir", "deny"),
    ("default", "write_file", True, "", "ask"),
    ("default", "delete", True, "", "ask"),
    ("acceptEdits", "write_file", True, "", "allow"),
    ("acceptEdits", "edit_file", True, "", "allow"),
    ("acceptEdits", "delete", True, "", "ask"),
    ("acceptEdits", "run_cmd", True, "dir", "ask"),
    ("auto", "delete", True, "", "allow"),
    ("auto", "write_file", False, "", "ask"),
    ("auto", "run_cmd", True, "git status", "allow"),
    ("auto", "run_cmd", True, "python -m pytest -q", "allow"),
    ("auto", "run_cmd", True, "git status && del x", "ask"),
    ("auto", "run_cmd", True, "pip install evil", "ask"),
    ("bypassPermissions", "delete", False, "", "allow"),
    ("bypassPermissions", "run_cmd", True, "rm -rf /", "deny"),
    ("bypassPermissions", "run_cmd", True, "format C:", "deny"),
    ("bypassPermissions", "run_cmd", True, "npm run build", "allow"),
    ("weird", "write_file", True, "", "ask"),
    ("auto", "made_up_tool", True, "", "ask"),
])
def test_decide_matrix(mode, tool, inside, cmd, want):
    assert permissions.decide(mode, tool, inside, cmd) == want


def test_broker_allow_deny_and_expiry():
    b = permissions.PermissionBroker()
    pid = b.ask({"tool": "write_file", "summary": "x"})
    assert [p["id"] for p in b.pending()] == [pid]
    assert b.wait(pid, 0) is None
    assert b.resolve(pid, "allow") is True
    assert b.resolve(pid, "deny") is False  # already answered
    assert b.wait(pid, 0) == "allow"
    assert b.wait(pid, 0) == "deny"  # gone
    assert b.resolve("nope", "allow") is False
    pid2 = b.ask({"tool": "delete"})
    assert b.resolve(pid2, "maybe") is False
    assert b.cancel_all() == 1 and b.wait(pid2, 0) == "deny"


def test_broker_always_is_per_kind_and_inside_only():
    b = permissions.PermissionBroker()
    pid = b.ask({"tool": "edit_file"})
    b.resolve(pid, "always")
    assert b.wait(pid, 0) == "allow"
    assert b.check("default", "write_file", True) == "allow"
    assert b.check("default", "write_file", False) == "ask"
    assert b.check("default", "delete", True) == "ask"
    assert b.check("plan", "write_file", True) == "deny"
    b.reset_always()
    assert b.check("default", "write_file", True) == "ask"


def test_broker_wait_unblocks_from_other_thread():
    b = permissions.PermissionBroker()
    pid = b.ask({"tool": "run_cmd"})
    threading.Timer(0.05, lambda: b.resolve(pid, "deny")).start()
    assert b.wait(pid, 2) == "deny"


# ---------- agent tools ----------

def test_parse_and_strip_tool_calls():
    text = ('Plan.\n<tool name="write_file"><path>a.txt</path><content>\nhello\n</content></tool>\n'
            "<TOOL name='run_cmd'><cmd>dir</cmd></TOOL> end")
    calls = agent.parse_tool_calls(text)
    assert [c["name"] for c in calls] == ["write_file", "run_cmd"]
    assert calls[0]["params"]["path"] == "a.txt" and calls[1]["params"]["cmd"] == "dir"
    assert "<tool" not in agent.strip_tool_calls(text).lower()
    assert agent.parse_tool_calls("") == [] and agent.parse_tool_calls(None) == []


def test_local_tools_file_lifecycle(tmp_path):
    t = agent.LocalTools(tmp_path)
    ok, out = t.run({"name": "write_file", "params": {"path": "src/app.py", "content": "\nprint('a')\nprint('b')\n"}})
    assert ok and (tmp_path / "src/app.py").read_text() == "print('a')\nprint('b')\n"
    assert t.run({"name": "read_file", "params": {"path": "src/app.py"}}) == (True, "print('a')\nprint('b')\n")
    ok, out = t.run({"name": "edit_file", "params": {"path": "src/app.py", "old_text": "print('b')", "new_text": "print('c')"}})
    assert ok and "print('c')" in (tmp_path / "src/app.py").read_text()
    ok, out = t.run({"name": "edit_file", "params": {"path": "src/app.py", "old_text": "print", "new_text": "x"}})
    assert not ok and "2 places" in out
    ok, out = t.run({"name": "edit_file", "params": {"path": "src/app.py", "old_text": "absent", "new_text": "x"}})
    assert not ok and "not found" in out
    assert t.run({"name": "ls", "params": {"path": "."}})[1].startswith("src/")
    assert "src/app.py:1:" in t.run({"name": "search", "params": {"pattern": "print\\('a", "path": "."}})[1]
    assert t.run({"name": "search", "params": {"pattern": "(", "path": "."}})[0]  # bad regex falls back to literal
    assert t.run({"name": "mkdir", "params": {"path": "a/b"}})[0] and (tmp_path / "a/b").is_dir()
    assert t.run({"name": "delete", "params": {"path": "src"}})[0] and not (tmp_path / "src").exists()
    ok, out = t.run({"name": "delete", "params": {"path": "."}})
    assert not ok and "refusing" in out
    assert not t.run({"name": "delete", "params": {"path": "missing.txt"}})[0]
    assert not t.run({"name": "teleport", "params": {}})[0]


def test_edit_file_keeps_crlf(tmp_path):
    f = tmp_path / "w.txt"
    f.write_bytes(b"one\r\ntwo\r\nthree\r\n")
    ok, _ = agent.LocalTools(tmp_path).run({"name": "edit_file", "params": {"path": "w.txt", "old_text": "one\ntwo", "new_text": "1\n2"}})
    assert ok and f.read_bytes() == b"1\r\n2\r\nthree\r\n"


def test_resolve_flags_paths_outside(tmp_path):
    t = agent.LocalTools(tmp_path / "proj")
    assert t.resolve("../x")[1] is False
    assert t.resolve(str(tmp_path / "elsewhere"))[1] is False
    assert t.resolve("ok/../fine.txt")[1] is True
    assert t.describe({"name": "write_file", "params": {"path": "../x", "content": "a"}})["inside"] is False


def test_describe_shows_diff_and_command(tmp_path):
    t = agent.LocalTools(tmp_path)
    (tmp_path / "a.txt").write_text("old\n")
    d = t.describe({"name": "write_file", "params": {"path": "a.txt", "content": "new\n"}})
    assert d["summary"].startswith("Overwrite") and "-old" in d["diff"] and "+new" in d["diff"]
    assert t.describe({"name": "write_file", "params": {"path": "b.txt", "content": "x"}})["summary"].startswith("Create")
    assert t.describe({"name": "run_cmd", "params": {"cmd": "echo hi"}})["command"] == "echo hi"


def test_run_cmd_and_format_results(tmp_path):
    ok, out = agent.LocalTools(tmp_path).run({"name": "run_cmd", "params": {"cmd": "echo hello"}})
    assert ok and out.startswith("exit code 0") and "hello" in out
    text = agent.format_results([({"name": "ls", "params": {"path": "."}}, "ok", "a/"),
                                 ({"name": "run_cmd", "params": {"cmd": "x"}}, "denied by the user", "")])
    assert "[1] ls .: ok" in text and "[2] run_cmd x: denied by the user" in text


# ---------- workspace mirroring ----------

def test_plan_apply_mirror_and_manifest(tmp_path):
    root = tmp_path / "proj"
    files = [{"path": "index.html", "content": "<h1>a</h1>"}, {"path": "src/app.js", "content": "x"},
             {"path": "../evil.txt", "content": "no"}, {"path": "/abs.txt", "content": "no"}, {"path": "bin.png", "content": None}]
    plan = workspace.plan_project(root, files)
    assert sorted(plan["writes"]) == ["abs.txt", "index.html", "src/app.js"] and plan["skipped"] == 2
    assert workspace.apply_project(plan) == (3, 0)
    assert not (tmp_path / "evil.txt").exists()
    (root / "mine.txt").write_text("user file")
    plan2 = workspace.plan_project(root, [{"path": "index.html", "content": "<h1>a</h1>"}])
    assert plan2["unchanged"] == 1 and not plan2["writes"]
    assert plan2["deletes"] == ["abs.txt", "src/app.js"]
    assert workspace.apply_project(plan2, write=True, delete=False) == (0, 0)
    assert (root / "src/app.js").exists()
    plan3 = workspace.plan_project(root, [{"path": "index.html", "content": "<h1>a</h1>"}])
    assert plan3["deletes"] == ["abs.txt", "src/app.js"]  # still tracked after a declined delete
    workspace.apply_project(plan3)
    assert not (root / "src/app.js").exists() and (root / "mine.txt").exists()


def test_zip_and_listing(tmp_path, monkeypatch):
    root = workspace.project_dir("0123456789abcdef", "My App!", "a", base=tmp_path)
    assert root == (tmp_path / "my-app-01234567" / "model-a").resolve()
    workspace.apply_project(workspace.plan_project(root, [{"path": "index.html", "content": "hi"}]))
    import io
    import zipfile
    names = zipfile.ZipFile(io.BytesIO(workspace.zip_dir(root))).namelist()
    assert names == ["index.html"]
    listed = workspace.list_projects(tmp_path)
    assert listed[0]["name"] == "my-app-01234567" and listed[0]["models"] == ["model-a"]
    assert workspace.slug("***") == "project" and workspace.webdev_files({"data": {"files": [{"path": "a"}, 3]}}) == [{"path": "a"}]


# ---------- engine ----------

def test_engine_reorders_out_of_order_pushes():
    eng = BrowserEngine()
    q = queue.Queue()
    eng._streams["r"] = {"q": q, "next": 0, "held": {}}
    eng._deliver("r", 2, "end", None)
    eng._deliver("r", 1, "chunk", "b")
    assert q.empty()
    eng._deliver("r", 0, "status", 200)
    assert [q.get_nowait() for _ in range(3)] == [("status", 200), ("chunk", "b"), ("end", None)]
    eng._deliver("unknown", 0, "status", 200)  # ignored


def test_engine_response_reads_stream():
    eng = BrowserEngine()
    q = queue.Queue()
    eng._streams["r"] = {"q": q, "next": 0, "held": {}}
    for i, item in enumerate([("status", 200), ("chunk", "ab"), ("chunk", "c"), ("end", None)]):
        eng._deliver("r", i, *item)
    r = EngineResponse(eng, "r", q, 5)
    assert r.status_code == 200 and r.ok and r.text == "abc" and "r" not in eng._streams


def test_engine_response_error_before_status():
    eng = BrowserEngine()
    q = queue.Queue()
    eng._streams["r"] = {"q": q, "next": 0, "held": {}}
    eng._deliver("r", 0, "error", "TypeError: Failed to fetch")
    r = EngineResponse(eng, "r", q, 5)
    assert r.status_code == 0 and "Failed to fetch" in r.error and r.text == ""


class _Fake:
    def __init__(self, status, text):
        self.status_code, self.text, self.error = status, text, "boom"


@pytest.mark.parametrize("status,text,user,err", [
    (200, '{"user": {"email": "a@b.c", "id": "1"}}', {"email": "a@b.c", "id": "1"}, None),
    (200, '{"user": null}', None, "Not signed in"),
    (401, "", None, "Not signed in"),
    (0, "", None, "Network error: boom"),
    (502, "", None, "HTTP 502"),
    (200, "<html>", None, "arena.ai sent an unexpected /api/me reply"),
])
def test_engine_get_me_parsing(status, text, user, err, monkeypatch):
    eng = BrowserEngine()
    eng.window, eng.loaded = object(), True
    monkeypatch.setattr(eng, "request", lambda *a, **k: _Fake(status, text))
    assert eng.get_me(timeout=1) == (user, err)


def test_engine_get_me_waits_for_challenge():
    eng = BrowserEngine()
    eng.window, eng.challenge = object(), "cloudflare"
    assert eng.get_me(timeout=0.3) == (None, "arena.ai is waiting for a cloudflare check")


# ---------- Flask API ----------

class FakeClient:
    def __init__(self):
        self.cookie_str = "arena-auth-prod-v1.0=base64-x"
        self.eval_id = None
        self.sources = []
        self.active_mode = "battle"
        self.active_modality = "chat"

    def get_me(self):
        return {"email": "t@e.st"}, None

    def sync_cookies(self):
        pass


class FakeResp:
    def __init__(self, lines=(), status=200, text=""):
        self.status_code, self._lines, self._text, self.error = status, list(lines), text, None

    def iter_text(self):
        for line in self._lines:
            yield line + "\n"

    @property
    def text(self):
        return self._text


@pytest.fixture
def web(tmp_path, monkeypatch):
    from arena.web import app as appmod
    cfg = {}
    monkeypatch.setattr(appmod, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(appmod, "save_config", lambda c: cfg.update(c))
    monkeypatch.setattr(workspace, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(appmod, "COOKIE_FILE", tmp_path / "cookies.txt")
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(accounts, "COOKIE_FILE", tmp_path / "accounts-cookies.txt")
    monkeypatch.setattr(appmod, "CHATS_DIR", tmp_path / "chats")
    monkeypatch.setattr(appmod.ENGINE, "window", None)
    monkeypatch.setattr(appmod, "_client", FakeClient())
    monkeypatch.setattr(appmod, "_ui_mode", "battle")
    monkeypatch.setattr(appmod, "_ui_modality", "auto")
    monkeypatch.setattr(appmod, "_current_chat_id", None)
    monkeypatch.setattr(appmod, "BROKER", permissions.PermissionBroker())
    appmod._me_cache.update(t=0.0, user=None, err=None)
    sent = []

    def use(*responses):
        it = iter(responses)

        def fake_send(client, path, body):
            sent.append((path, body))
            return next(it)
        monkeypatch.setattr(appmod, "_send", fake_send)
    appmod.app.config["TESTING"] = True
    return appmod, appmod.app.test_client(), cfg, use, sent


def events(resp):
    return [json.loads(chunk[6:]) for chunk in resp.get_data(as_text=True).split("\n\n") if chunk.startswith("data: ")]


def test_login_rejects_garbage_and_empty_clipboard(web, monkeypatch):
    appmod, c, *_ = web
    r = c.post("/api/login", json={"method": "manual", "cookie": "hello=world"})
    assert r.status_code == 400 and "arena-auth-prod-v1" in r.get_json()["error"]
    assert c.post("/api/login", json={"method": "manual"}).status_code == 400
    monkeypatch.setattr(appmod, "get_clipboard_text", lambda: "")
    r = c.post("/api/login", json={"method": "clipboard"})
    assert r.status_code == 400 and "clipboard is empty" in r.get_json()["error"]
    r = c.post("/api/login", json={"method": "window"})
    assert r.status_code == 400 and "desktop app" in r.get_json()["error"]
    assert c.get("/api/login/poll").get_json()["done"] is True


def test_guard_blocks_cross_origin_bad_host_and_non_json(web):
    _, c, *_ = web
    assert c.post("/api/new", headers={"Origin": "http://evil.test"}).status_code == 403
    assert c.post("/api/new", headers={"Origin": "http://localhost"}).status_code == 200
    assert c.get("/api/engine", headers={"Host": "evil.test"}).status_code == 403
    assert c.post("/api/settings", data="a=b", content_type="text/plain").status_code == 415


def test_status_without_engine(web):
    _, c, *_ = web
    s = c.get("/api/status").get_json()
    assert s["authenticated"] is True and s["email"] == "t@e.st" and s["desktop"] is False
    assert s["permission_mode"] == "default" and s["workspace"].endswith("workspace")


def _session_cookie(email, user_id, token):
    payload = {"user": {"id": user_id, "email": email, "user_metadata": {}}, "access_token": token}
    return "arena-auth-prod-v1.0=base64-" + base64.b64encode(json.dumps(payload).encode()).decode()


def _fake_arena(monkeypatch, appmod):
    class FakeArena:
        def __init__(self, cookie_str=None):
            self.cookie_str = cookie_str
            self.eval_id = None
            self.sources = []
            self.active_mode = "battle"
            self.active_modality = "chat"

        def get_me(self):
            info = parse_cookie_input(self.cookie_str or "")[2] or {}
            return ({"email": info.get("email")}, None) if info.get("email") else (None, "bad session")

        def sync_cookies(self):
            pass

    monkeypatch.setattr(appmod, "ArenaClient", FakeArena)


def test_accounts_switch_route_and_chat_scoping(web, monkeypatch):
    appmod, c, cfg, *_ = web
    _fake_arena(monkeypatch, appmod)
    a_cookie = _session_cookie("a@example.com", "ua", "ta")
    b_cookie = _session_cookie("b@example.com", "ub", "tb")
    accounts.remember(a_cookie)
    chat_a = str(uuid.uuid4())
    appmod._save_chat(chat_a, "A chat", [], mode="battle", modality="auto")
    accounts.remember(b_cookie)
    chat_b = str(uuid.uuid4())
    appmod._save_chat(chat_b, "B chat", [], mode="battle", modality="auto")

    listed = c.get("/api/accounts").get_json()
    assert [a["email"] for a in listed["accounts"]] == ["a@example.com", "b@example.com"]
    assert all("cookie" not in a for a in listed["accounts"])
    assert [x["id"] for x in appmod._list_chats()] == [chat_b]
    assert c.get(f"/api/chats/{chat_a}").status_code == 404

    a_id = next(a["id"] for a in listed["accounts"] if a["email"] == "a@example.com")
    r = c.post("/api/accounts/switch", json={"id": a_id})
    assert r.status_code == 200 and r.get_json()["ok"]
    assert accounts.active_account()["email"] == "a@example.com"
    assert [x["id"] for x in appmod._list_chats()] == [chat_a]
    assert c.get(f"/api/chats/{chat_a}").status_code == 200


def test_login_with_a_second_cookie_adds_an_account(web, monkeypatch):
    appmod, c, *_ = web
    _fake_arena(monkeypatch, appmod)
    a_cookie = _session_cookie("a@example.com", "ua", "ta")
    b_cookie = _session_cookie("b@example.com", "ub", "tb")
    accounts.remember(a_cookie)
    r = c.post("/api/login", json={"method": "manual", "cookie": b_cookie})
    assert r.status_code == 200 and r.get_json()["email"] == "b@example.com"
    assert [a["email"] for a in accounts.list_accounts()] == ["a@example.com", "b@example.com"]
    assert accounts.active_account()["email"] == "b@example.com"


def test_account_switch_imports_the_cookie_into_the_engine(web, monkeypatch):
    appmod, c, *_ = web
    a_cookie = _session_cookie("a@example.com", "ua", "ta")
    b_cookie = _session_cookie("b@example.com", "ub", "tb")
    accounts.remember(a_cookie)
    accounts.remember(b_cookie)

    class FakeEngine:
        window = object()
        challenge = None
        imported = []

        def import_cookies(self, cookie):
            self.imported.append(cookie)
            return True

        def wait_ready(self, timeout):
            return True

        def get_me(self):
            info = parse_cookie_input(self.imported[-1] if self.imported else "")[2] or {}
            return {"email": info.get("email")}, None

        def sync_to(self, client):
            pass

    eng = FakeEngine()
    monkeypatch.setattr(appmod, "ENGINE", eng)
    _fake_arena(monkeypatch, appmod)
    a_id = next(a["id"] for a in accounts.list_accounts() if a["email"] == "a@example.com")
    r = c.post("/api/accounts/switch", json={"id": a_id})
    assert r.status_code == 200 and r.get_json()["ok"]
    assert eng.imported[-1] == a_cookie
    assert accounts.active_account()["email"] == "a@example.com"


def test_account_switch_rejects_a_different_engine_session(web, monkeypatch):
    appmod, c, *_ = web
    a_cookie = _session_cookie("a@example.com", "ua", "ta")
    b_cookie = _session_cookie("b@example.com", "ub", "tb")
    accounts.remember(a_cookie)
    a_id = accounts.active_id()
    accounts.remember(b_cookie)
    accounts.set_active(a_id)

    class StuckEngine:
        window = object()
        challenge = None
        imported = []

        def import_cookies(self, cookie):
            self.imported.append(cookie)
            return True

        def wait_ready(self, timeout):
            return True

        def get_me(self):
            return {"email": "a@example.com"}, None

        def sync_to(self, client):
            pass

    eng = StuckEngine()
    monkeypatch.setattr(appmod, "ENGINE", eng)
    _fake_arena(monkeypatch, appmod)
    b_id = next(a["id"] for a in accounts.list_accounts() if a["email"] == "b@example.com")
    r = c.post("/api/accounts/switch", json={"id": b_id})
    assert r.status_code == 401
    assert accounts.active_id() == a_id
    assert eng.imported[-1] == a_cookie  # it put the previous session back


def test_logout_switches_to_the_next_saved_account(web, monkeypatch):
    appmod, c, *_ = web
    _fake_arena(monkeypatch, appmod)
    a_cookie = _session_cookie("a@example.com", "ua", "ta")
    b_cookie = _session_cookie("b@example.com", "ub", "tb")
    accounts.remember(a_cookie)
    accounts.remember(b_cookie)

    r = c.post("/api/logout", json={})
    data = r.get_json()
    a_id = next(a["id"] for a in accounts.list_accounts() if a["email"] == "a@example.com")
    assert r.status_code == 200 and data["active"] == a_id and data["switched_to"] == "a@example.com"
    assert [a["email"] for a in accounts.list_accounts()] == ["a@example.com"] and accounts.active_id() == a_id

    r = c.post("/api/logout", json={})
    assert r.status_code == 200 and r.get_json()["active"] is None
    assert accounts.list_accounts() == []


def test_models_refresh_query_forces_the_catalog(web, monkeypatch):
    appmod, c, *_ = web
    calls = []

    def fake_models(force=False):
        calls.append(force)
        return []

    monkeypatch.setattr(appmod, "sync_models", fake_models)
    assert c.get("/api/models?modality=chat").status_code == 200
    assert calls[-1] is False
    assert c.get("/api/models?modality=chat&refresh=1").status_code == 200
    assert calls[-1] is True


def test_agent_mode_is_auto_only(web):
    appmod, c, *_ = web
    r = c.post("/api/mode", json={"mode": "agent"}).get_json()
    assert r["mode"] == "agent" and r["modality"] == "auto"
    assert appmod._ui_modality == "auto"
    assert c.post("/api/modality", json={"modality": "video"}).status_code == 400
    assert c.post("/api/modality", json={"modality": "auto"}).status_code == 200
    c.post("/api/mode", json={"mode": "direct"})
    assert c.post("/api/modality", json={"modality": "video"}).get_json()["modality"] == "video"


def test_permission_mode_and_answers(web):
    _, c, cfg, *_ = web
    assert c.post("/api/permission-mode", json={"mode": "bogus"}).status_code == 400
    r = c.post("/api/permission-mode", json={"mode": "auto"}).get_json()
    assert r["mode"] == "auto" and cfg["permission_mode"] == "auto"
    assert c.get("/api/permission-mode").get_json()["mode"] == "auto"
    assert c.post("/api/permissions/nope", json={"decision": "allow"}).status_code == 404
    assert c.post("/api/permissions/nope", json={"decision": "sure"}).status_code == 400


def test_chat_validation(web):
    appmod, c, *_ = web
    assert c.post("/api/chat", json={"message": "  "}).status_code == 400
    appmod._ui_mode = "direct"
    r = c.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 400 and "Pick a model" in r.get_json()["error"]
    appmod._client.cookie_str = None
    assert c.post("/api/chat", json={"message": "hi", "model_id": "m"}).status_code == 401


def test_file_only_message_is_allowed(web):
    appmod, c, _, use, sent = web
    use(FakeResp(['a0:"seen"']))
    ev = events(c.post("/api/chat", json={"message": "", "attachments": [
        {"name": "shot.png", "contentType": "image/png", "url": "https://cdn.example/x.png"}]}))
    assert ev[-1]["type"] == "done"
    assert sent[0][1]["userMessage"]["experimental_attachments"][0]["name"] == "shot.png"
    assert appmod._load_chat(ev[0]["chat_id"])["title"] == "shot.png"


def test_chat_forwards_clean_attachments(web):
    _, c, _, use, sent = web
    use(FakeResp(['a0:"ok"']))
    events(c.post("/api/chat", json={"message": "look", "attachments": [
        {"name": "shot.png", "contentType": "image/png", "url": "https://cdn.example/x.png", "evil": "drop me"},
        {"name": "local.png", "contentType": "image/png", "url": "http://127.0.0.1/x.png"},
        {"name": "bad.txt", "contentType": "text/plain", "url": "javascript:alert(1)"},
        "not-a-dict",
    ]}))
    assert sent[0][1]["userMessage"]["experimental_attachments"] == [
        {"name": "shot.png", "contentType": "image/png", "url": "https://cdn.example/x.png"},
        {"name": "local.png", "contentType": "image/png", "url": "http://127.0.0.1/x.png"}]


def test_upload_route_inlines_text_and_uploads_binary(web, monkeypatch):
    appmod, c, *_ = web
    json_calls, puts = [], []

    def fake_json(client, path, payload, timeout=60):
        json_calls.append((path, payload))
        if path == contracts.PATHS["storage_upload"]:
            return {"uploadUrl": "https://upload.example/abc", "key": "/files/abc.png"}
        if path == contracts.PATHS["storage_signed"]:
            return {"url": "https://cdn.example/files/abc.png"}
        raise AssertionError(path)

    class Put:
        ok, status_code = True, 200

    monkeypatch.setattr(appmod, "_arena_json", fake_json)
    monkeypatch.setattr(appmod.requests, "put",
                        lambda url, data=None, headers=None, **kw: puts.append((url, data, headers)) or Put())
    r = c.post("/api/upload", json={"files": [
        {"name": "notes.txt", "type": "text/plain", "data": "hello", "binary": False},
        {"name": "tricky.txt", "type": "text/plain", "data": "data:not-a-url,hello", "binary": False},
        {"name": "shot.png", "type": "image/png", "data": "data:image/png;base64,iVBORw0KGgo=", "binary": True},
    ]})
    assert r.status_code == 200
    files = r.get_json()["files"]
    assert files[0]["text"] == "hello" and "attachment" not in files[0]
    assert files[1]["text"] == "data:not-a-url,hello"
    assert files[2]["attachment"] == {
        "name": "shot.png", "contentType": "image/png", "url": "https://cdn.example/files/abc.png"}
    assert json_calls == [
        (contracts.PATHS["storage_upload"], {"fileName": "shot.png", "contentType": "image/png"}),
        (contracts.PATHS["storage_signed"], {"key": "files/abc.png"}),
    ]
    assert puts[0][0] == "https://upload.example/abc" and puts[0][1].startswith(b"\x89PNG")
    assert puts[0][2] == {"Content-Type": "image/png"}


def test_upload_route_reads_native_files_and_rejects_big_ones(web, monkeypatch, tmp_path):
    appmod, c, *_ = web
    native = tmp_path / "notes.md"
    native.write_text("# hi")
    monkeypatch.setattr(appmod, "_arena_upload", lambda client, name, ctype, blob: {
        "name": name, "contentType": ctype, "url": "https://cdn.example/" + name})
    r = c.post("/api/upload", json={"files": [{"name": "notes.md", "path": str(native), "size": 0}]})
    assert r.status_code == 200 and r.get_json()["files"][0]["text"] == "# hi"
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (appmod.ATTACHMENT_MAX_BYTES + 1))
    r = c.post("/api/upload", json={"files": [{"name": "big.bin", "path": str(big)}]})
    assert r.status_code == 400 and "15 MB" in r.get_json()["error"]


def test_upload_route_needs_a_session(web):
    appmod, c, *_ = web
    appmod._client.cookie_str = None
    assert c.post("/api/upload", json={"files": [{"name": "a.txt", "data": "x"}]}).status_code == 401
    assert c.post("/api/upload", json={}).status_code == 400


def test_battle_chat_streams_both_lanes_and_saves(web):
    appmod, c, _, use, sent = web
    use(FakeResp(['a0:"Hello "', 'b0:"Hi"', 'a0:"there"', 'ad:{"finishReason":"stop"}']))
    ev = events(c.post("/api/chat", json={"message": "yo"}))
    assert ev[0]["type"] == "meta" and ev[0]["dual"] is True
    done = ev[-1]
    assert done["type"] == "done" and done["text_a"] == "Hello there" and done["text_b"] == "Hi"
    path, body = sent[0]
    assert path == contracts.PATHS["create"] and body["mode"] == "battle" and "modelAId" not in body
    assert appmod._client.eval_id == body["id"]
    use(FakeResp(['a0:"again"']))
    events(c.post("/api/chat", json={"message": "more", "chat_id": ev[0]["chat_id"]}))
    assert sent[1][0] == contracts.PATHS["post"].format(eval_id=body["id"]) and "mode" not in sent[1][1]


def test_direct_video_sends_video_modality_and_emits_media(web):
    appmod, c, _, use, sent = web
    appmod._ui_mode = "direct"
    appmod._ui_modality = "video"
    use(FakeResp(['a2:' + json.dumps([
        {"type": "video", "url": "https://cdn.example/clip.mp4", "mimeType": "video/mp4"}
    ])]))
    ev = events(c.post("/api/chat", json={"message": "make a clip", "model_id": "video-model"}))
    assert sent[0][1]["modality"] == "video"
    assert sent[0][1]["modelAId"] == "video-model"
    media = [e for e in ev if e["type"] == "media"]
    assert media and media[0]["kind"] == "video"
    assert media[0]["url"] == "https://cdn.example/clip.mp4"


def test_challenge_without_engine_explains(web):
    _, c, _, use, _ = web
    use(FakeResp(status=403, text='{"error":"recaptcha validation failed"}'))
    ev = events(c.post("/api/chat", json={"message": "hi"}))
    err = [e for e in ev if e["type"] == "error"][0]
    assert err["code"] == "challenge" and "arena-ai.exe" in err["message"]
    assert ev[-1]["type"] == "done"


def test_expired_eval_starts_new_conversation(web):
    appmod, c, _, use, sent = web
    import uuid
    cid = str(uuid.uuid4())
    appmod._save_chat(cid, title="old", messages=[], mode=appmod._ui_mode, eval_id="old-eval")
    use(FakeResp(status=404, text="not found"), FakeResp(['a0:"fresh"']))
    ev = events(c.post("/api/chat", json={"message": "hi", "chat_id": cid}))
    assert any(e["type"] == "notice" for e in ev) and ev[-1]["text_a"] == "fresh"
    assert "mode" not in sent[0][1] and sent[1][1]["mode"] == "battle"


def _tool_line(text):
    return "a0:" + json.dumps(text)


def test_agent_writes_file_in_accept_edits(web):
    appmod, c, cfg, use, sent = web
    cfg["permission_mode"] = "acceptEdits"
    appmod._ui_mode = "agent"
    use(FakeResp([_tool_line('Writing.<tool name="write_file"><path>hello.txt</path><content>\nhi\n</content></tool>')]),
        FakeResp(['a0:"Done."']))
    ev = events(c.post("/api/chat", json={"message": "make hello", "model_id": "m1"}))
    root = workspace.PROJECTS_DIR / "workspace"
    assert (root / "hello.txt").read_text() == "hi\n"
    result = [e for e in ev if e["type"] == "tool_result"][0]
    assert result["ok"] and result["status"] == "ok"
    assert "User message:\nmake hello" in sent[0][1]["userMessage"]["content"] and sent[0][1]["modelAId"] == "m1"
    assert sent[1][1]["userMessage"]["content"].startswith("Tool results:") and "mode" not in sent[1][1]


def test_agent_plan_mode_blocks_writes(web):
    appmod, c, cfg, use, _ = web
    cfg["permission_mode"] = "plan"
    appmod._ui_mode = "agent"
    use(FakeResp([_tool_line('<tool name="write_file"><path>x.txt</path><content>a</content></tool>')]), FakeResp(['a0:"Plan: 1. write x"']))
    ev = events(c.post("/api/chat", json={"message": "plan", "model_id": "m1"}))
    assert not (workspace.PROJECTS_DIR / "workspace" / "x.txt").exists()
    assert [e for e in ev if e["type"] == "tool_result"][0]["status"].startswith("blocked: plan mode")


def test_agent_asks_and_user_denies(web):
    appmod, c, cfg, use, _ = web
    appmod._ui_mode = "agent"
    use(FakeResp([_tool_line('<tool name="delete"><path>keep.txt</path></tool>')]), FakeResp(['a0:"ok"']))
    root = workspace.PROJECTS_DIR / "workspace"
    root.mkdir(parents=True)
    (root / "keep.txt").write_text("x")

    def answer():
        for _ in range(100):
            pending = appmod.BROKER.pending()
            if pending:
                appmod.BROKER.resolve(pending[0]["id"], "deny")
                return
            time.sleep(0.05)
    threading.Thread(target=answer, daemon=True).start()
    ev = events(c.post("/api/chat", json={"message": "clean", "model_id": "m1"}))
    assert (root / "keep.txt").exists()
    assert any(e["type"] == "permission" for e in ev)
    assert [e for e in ev if e["type"] == "tool_result"][0]["status"] == "denied by the user"


def test_agent_has_no_tool_round_cap(web):
    appmod, c, cfg, use, sent = web
    cfg["permission_mode"] = "acceptEdits"
    appmod._ui_mode = "agent"
    rounds = [FakeResp([_tool_line(f'<tool name="write_file"><path>f{i}.txt</path><content>{i}</content></tool>')])
              for i in range(12)]
    use(*rounds, FakeResp(['a0:"All done."']))
    ev = events(c.post("/api/chat", json={"message": "write twelve files", "model_id": "m1"}))
    root = workspace.PROJECTS_DIR / "workspace"
    assert all((root / f"f{i}.txt").read_text() == str(i) for i in range(12))
    assert len([e for e in ev if e["type"] == "tool_result"]) == 12
    assert not any("Stopped after" in (e.get("text") or "") for e in ev)
    assert ev[-1]["type"] == "done" and "All done." in ev[-1]["text_a"]


def test_agent_resumes_after_rate_limit(web, monkeypatch):
    appmod, c, cfg, use, sent = web
    cfg["permission_mode"] = "acceptEdits"
    appmod._ui_mode = "agent"
    monkeypatch.setattr(appmod.time, "sleep", lambda seconds: None)  # the real wait is 60s
    use(FakeResp([_tool_line('<tool name="write_file"><path>ok.txt</path><content>yes</content></tool>')]),
        FakeResp(status=429, text="slow down"),
        FakeResp(['a0:"Finished after the limit."']))
    ev = events(c.post("/api/chat", json={"message": "write ok.txt", "model_id": "m1"}))
    assert (workspace.PROJECTS_DIR / "workspace" / "ok.txt").read_text() == "yes"
    assert any(e["type"] == "notice" and "rate-limited" in (e.get("text") or "") for e in ev)
    assert ev[-1]["type"] == "done" and "Finished after the limit." in ev[-1]["text_a"]
    assert len(sent) == 3


def test_tool_results_keep_the_full_read(web):
    output = "x" * 30_000
    lines = agent._result_lines([({"name": "read_file", "params": {"path": "big.txt"}}, "ok", output)])
    assert len(lines[1]) == len(output)


def _webdev_line(lane, content):
    item = {"type": "webdev", "event": "init", "templateKind": "vanilla",
            "files": [{"path": "index.html", "content": content}]}
    return f"{lane}2:" + json.dumps([item])


def test_code_mode_saves_files_locally(web):
    appmod, c, cfg, use, _ = web
    cfg["permission_mode"] = "acceptEdits"
    appmod._ui_modality = "code"
    use(FakeResp([_webdev_line("a", "<h1>A</h1>"), _webdev_line("b", "<h1>B</h1>")]))
    ev = events(c.post("/api/chat", json={"message": "landing page"}))
    written = {e["model"]: e for e in ev if e["type"] == "files_written"}
    assert written["a"]["saved"] and written["a"]["written"] == 1
    assert Path(written["b"]["root"], "index.html").read_text() == "<h1>B</h1>"
    assert written["a"]["preview"].startswith("http://127.0.0.1:")
    assert c.post("/api/workspace/open", json={"path": "C:/Windows"}).status_code == 403
    assert c.get("/api/workspace/zip?path=" + written["a"]["root"]).status_code == 200


def test_plan_mode_defers_code_save_until_user_clicks(web):
    appmod, c, cfg, use, _ = web
    cfg["permission_mode"] = "plan"
    appmod._ui_modality = "code"
    use(FakeResp([_webdev_line("a", "<p>x</p>")]))
    ev = events(c.post("/api/chat", json={"message": "page"}))
    fw = [e for e in ev if e["type"] == "files_written"][0]
    assert fw["saved"] is False and not Path(fw["root"], "index.html").exists()
    r = c.post("/api/workspace/save", json={"chat_id": ev[0]["chat_id"], "lane": "a"}).get_json()
    assert r["ok"] and r["written"] == 1 and Path(fw["root"], "index.html").exists()
    assert c.post("/api/workspace/save", json={"chat_id": "nope", "lane": "a"}).status_code == 404


def test_workspace_set_rules(web, tmp_path):
    _, c, cfg, *_ = web
    assert c.post("/api/workspace/set", json={"path": "relative/dir"}).status_code == 400
    assert c.post("/api/workspace/set", json={"path": str(Path.home())}).status_code == 400
    r = c.post("/api/workspace/set", json={"path": str(tmp_path / "proj")}).get_json()
    assert r["ok"] and cfg["workspace_dir"] == str((tmp_path / "proj").resolve())


def test_media_save_rules(web):
    _, c, *_ = web
    assert c.post("/api/media/save", json={"url": "http://x.test/a.png"}).status_code == 400
    assert c.post("/api/media/save", json={"url": "https://127.0.0.1/a.png"}).status_code == 400
    r = c.post("/api/media/save", json={"url": "data:image/png;base64,iVBORw0KGgo="}).get_json()
    assert r["ok"] and Path(r["path"]).read_bytes().startswith(b"\x89PNG")


def test_safe_resolve_blocks_outside_home(web):
    appmod, *_ = web
    assert appmod._safe_resolve(".") == Path.home().resolve()
    with pytest.raises(PermissionError):
        appmod._safe_resolve(str(Path.home().parent))
    with pytest.raises(PermissionError):
        appmod._safe_resolve("../")


def test_check_panel_stays_below_recaptcha_popup():
    import re
    from arena import engine
    z = int(re.search(r"z-index:(\d+)", engine._CHECK_JS).group(1))
    assert z < 2000000000  # Google's picture popup must render above the panel
    assert "arena-desktop-hide" not in engine._CHECK_JS  # nothing may delete the checkbox mid-check


def test_engine_shows_and_hides_through_dock():
    from arena.engine import BrowserEngine

    class FakeDock:
        visible = False

        def __init__(self):
            self.calls = []

        def show(self):
            self.calls.append("show")
            self.visible = True
            return True

        def hide(self):
            self.calls.append("hide")
            self.visible = False

    class NoWindow:
        def show(self):
            raise AssertionError("a docked engine must not open a second window")

        hide = show

    e = BrowserEngine()
    e.window, e.dock = NoWindow(), FakeDock()
    e._present()
    e.hide()
    assert e.dock.calls == ["show", "hide"]
    e.challenge, e.login_open, e.dock.visible = "recaptcha", True, True
    e.close_pane()
    assert e.challenge is None and e.login_open is False


def test_chats_keep_their_own_history(web):
    appmod, c, _, use, sent = web
    use(FakeResp(['a0:"one"']))
    a = events(c.post("/api/chat", json={"message": "first"}))[0]["chat_id"]
    b = c.post("/api/new").get_json()["chat_id"]
    use(FakeResp(['a0:"two"']))
    events(c.post("/api/chat", json={"message": "second", "chat_id": b}))
    assert [m["text"] for m in appmod._load_chat(b)["messages"]] == ["second", "two"]
    assert [m["text"] for m in appmod._load_chat(a)["messages"]] == ["first", "one"]


def test_failed_reply_is_saved_with_its_error(web):
    appmod, c, _, use, sent = web
    use(FakeResp(status=500, text="boom"))
    ev = events(c.post("/api/chat", json={"message": "x"}))
    last = appmod._load_chat(ev[0]["chat_id"])["messages"][-1]
    assert last["role"] == "assistant" and last["text"] == "" and last.get("error")


def test_two_model_tools_keep_each_copy_apart(tmp_path):
    (tmp_path / "keep.txt").write_bytes(b"one\ntwo\n")
    (tmp_path / "option-b").mkdir()
    (tmp_path / "option-b" / "x.txt").write_text("start")
    a = agent.LocalTools(tmp_path, tmp_path / agent.LANE_DIRS["a"])
    ok, _ = a.run({"name": "write_file", "params": {"path": "help.py", "content": "start"}})
    assert ok and (tmp_path / "option-a" / "help.py").read_text() == "start" and not (tmp_path / "help.py").exists()
    info = a.describe({"name": "edit_file", "params": {"path": "keep.txt", "old_text": "two", "new_text": "2"}})
    assert info["rel"] == "option-a/keep.txt" and "+2" in info["diff"]
    ok, _ = a.run({"name": "edit_file", "params": {"path": "keep.txt", "old_text": "two", "new_text": "2"}})
    assert ok and (tmp_path / "keep.txt").read_text() == "one\ntwo\n"
    assert a.run({"name": "read_file", "params": {"path": "keep.txt"}})[1] == "one\n2\n"
    listing = a.run({"name": "ls", "params": {"path": "."}})[1]
    assert "help.py" in listing and "keep.txt" in listing and "option-" not in listing
    found = a.run({"name": "search", "params": {"pattern": "start"}})[1]
    assert "option-a/help.py" in found and "option-b" not in found


def test_tool_tags_parse_without_quotes_and_strip_cleanly():
    calls = agent.parse_tool_calls("<tool name=ls><path>.</path></tool>")
    assert calls == [{"name": "ls", "params": {"path": "."}}]
    assert agent.strip_tool_calls('ok ```xml\n<tool name="ls"><path>.</path></tool>\n``` done') == "ok  done"


def test_battle_models_get_tools_once_a_folder_is_picked(web, tmp_path):
    appmod, c, cfg, use, sent = web
    cfg.update(permission_mode="acceptEdits", workspace_dir=str(tmp_path / "ws"))
    call = '<tool name="write_file"><path>help.py</path><content>start this right now</content></tool>'
    use(FakeResp([_tool_line(call), "b0:" + json.dumps(call.replace("start", "begin"))]),
        FakeResp(['a0:"done"', 'b0:"done"']))
    ev = events(c.post("/api/chat", json={"message": "Create help.py"}))
    ws = tmp_path / "ws"
    assert (ws / "option-a" / "help.py").read_text() == "start this right now"
    assert (ws / "option-b" / "help.py").read_text() == "begin this right now"
    assert "User message:\nCreate help.py" in sent[0][1]["userMessage"]["content"]
    second = sent[1][1]["userMessage"]["content"]
    assert second.startswith("Tool results for both replies") and "Reply A:" in second and "Reply B:" in second
    assert sorted(e["model"] for e in ev if e["type"] == "tool_result") == ["a", "b"]
    saved = appmod._load_chat(ev[0]["chat_id"])["messages"][-1]
    assert "<tool" not in saved["text"] + saved["text_b"] and {t["lane"] for t in saved["tools"]} == {"a", "b"}


def test_plain_chat_without_a_picked_folder_gets_no_tool_guide(web):
    appmod, c, cfg, use, sent = web
    use(FakeResp(['a0:"hi"', 'b0:"hello"']))
    events(c.post("/api/chat", json={"message": "hi"}))
    assert sent[0][1]["userMessage"]["content"] == "hi"


def test_generated_media_is_saved_to_the_picked_folder(web, tmp_path, monkeypatch):
    appmod, c, cfg, use, sent = web
    cfg["workspace_dir"] = str(tmp_path / "ws")

    class Got:
        content, headers = b"PNG", {"content-type": "image/png"}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(appmod.requests, "get", lambda url, timeout: Got())
    out = list(appmod._save_media({"url": "https://cdn.example/img/cat.png", "kind": "image"}, "a", {"title": "A cat"}))
    saved = list((tmp_path / "ws").glob("*-a-*.png"))
    assert len(saved) == 1 and saved[0].read_bytes() == b"PNG" and "Saved to" in out[0]


def test_sandbox_ops_from_arena_tool_calls():
    from arena import contracts
    op = contracts.sandbox_op({"toolCallId": "1", "toolName": "create_file", "args": {"path": "src/a.ts", "content": "x"}})
    assert op["kind"] == "write" and op["path"] == "src/a.ts" and op["content"] == "x"
    op = contracts.sandbox_op({"toolCallId": "2", "toolName": "str_replace_based_edit_tool",
                               "args": json.dumps({"command": "str_replace", "path": "a.ts", "old_str": "x", "new_str": "y"})})
    assert op["kind"] == "edit" and (op["old"], op["new"]) == ("x", "y")
    assert contracts.sandbox_op({"toolName": "bash", "args": {"command": "npm install"}})["kind"] == "run"
    assert contracts.sandbox_op({"toolName": "read_file", "args": {"path": "package.json"}})["kind"] == "read"
    assert contracts.parse_line('aa:{"toolCallId":"1","result":"ok"}') == ("a", "tool_result", {"toolCallId": "1", "result": "ok"})
    assert contracts.parse_line('b9:{"toolCallId":"1"}')[:2] == ("b", "tool_call")


def test_code_answer_is_copied_into_the_picked_folder_and_local_edits_go_back(web, tmp_path):
    appmod, c, cfg, use, sent = web
    cfg.update(permission_mode="acceptEdits", workspace_dir=str(tmp_path / "ws"))
    appmod._ui_mode, appmod._ui_modality = "direct", "code"
    create = {"toolCallId": "t1", "toolName": "create_file", "args": {"path": "src/App.tsx", "content": "hello\nworld\n"}}
    edit = {"toolCallId": "t2", "toolName": "edit_file", "args": {"path": "src/App.tsx", "old_str": "world", "new_str": "arena"}}
    use(FakeResp(['a0:"I will create src/App.tsx."', "a9:" + json.dumps(create), 'aa:{"toolCallId":"t1","result":"ok"}',
                  "a9:" + json.dumps(edit), 'aa:{"toolCallId":"t2","result":{"url":"https://x1.arena.site/"}}', 'a0:"Done."']))
    ev = events(c.post("/api/chat", json={"message": "build", "model_id": "m1"}))
    app_tsx = tmp_path / "ws" / "src" / "App.tsx"
    assert app_tsx.read_bytes() == b"hello\narena\n"
    rows = [e for e in ev if e["type"] == "sandbox"]
    assert [r["verb"] for r in rows] == ["Created", "Edited"] and (rows[1]["add"], rows[1]["del"]) == (1, 1)
    assert any(e["type"] == "preview" and e["url"] == "https://x1.arena.site/" for e in ev)
    cid = ev[0]["chat_id"]
    assert [r["verb"] for r in appmod._load_chat(cid)["messages"][-1]["sandbox"]] == ["Created", "Edited"]
    app_tsx.write_bytes(b"hello\nmine\n")
    use(FakeResp(['a0:"ok"']))
    events(c.post("/api/chat", json={"message": "next", "model_id": "m1", "chat_id": cid}))
    content = sent[-1][1]["userMessage"]["content"]
    assert "--- src/App.tsx ---\nhello\nmine\n" in content and content.endswith("My message:\nnext")

