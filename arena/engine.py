"""
Embedded arena.ai engine.

A hidden WebView2 window stays on https://arena.ai. Chats are sent from that
page, so arena's own reCAPTCHA and Cloudflare checks run in a real browser with
the user's real session. When arena asks for a visible check (reCAPTCHA
checkbox, Cloudflare "Just a moment..."), the window is shown to the human.
Nothing here solves, mints or fakes a challenge.

Rotation resilience: only endpoint paths from arena.contracts are used, and the
reCAPTCHA key is read from the live page's <script src="...render=KEY"> tag.
"""

import json
import logging
import queue
import threading
import time
import uuid
from typing import Dict, Optional, Tuple

from arena import contracts

LOG = logging.getLogger("arena.desktop")

# Runs inside arena.ai. Each push carries a sequence number because pywebview
# dispatches every js_api call on its own thread, so arrival order is not guaranteed.
_FETCH_JS = r"""
(function (rid, path, method, body, v3key, action) {
  var seq = 0;
  function push(kind, data) { window.pywebview.api.push(rid, seq++, kind, data); }
  function wait(ms) { return new Promise(function (ok) { setTimeout(ok, ms); }); }
  (async function () {
    for (var i = 0; i < 50 && !(window.pywebview && window.pywebview.api && window.pywebview.api.push); i++) await wait(100);
    try {
      if (body && 'recaptchaV3Token' in body && !body.recaptchaV2Token) {
        var tag = document.querySelector('script[src*="recaptcha"][src*="render="]');
        var key = (tag && new URL(tag.src).searchParams.get('render')) || v3key;
        if (!window.grecaptcha && key) {
          await Promise.race([wait(8000), new Promise(function (ok) {
            var s = document.createElement('script');
            s.src = 'https://www.google.com/recaptcha/enterprise.js?render=' + key;
            s.onload = ok; s.onerror = ok; document.head.appendChild(s);
          })]);
        }
        var g = window.grecaptcha && (window.grecaptcha.enterprise || window.grecaptcha);
        if (g && g.execute) {
          await Promise.race([wait(8000), new Promise(function (ok) { g.ready ? g.ready(ok) : ok(); })]);
          try { body.recaptchaV3Token = await Promise.race([g.execute(key, {action: action}), wait(15000).then(function () { return null; })]); } catch (e) {}
        }
      }
      var res = await fetch(path, {method: method, credentials: 'include',
        headers: body ? {'Content-Type': 'application/json'} : {},
        body: body ? JSON.stringify(body) : undefined});
      push('status', res.status);
      if (res.body) {
        var rd = res.body.getReader(), dec = new TextDecoder();
        for (;;) {
          var r = await rd.read();
          if (r.done) break;
          push('chunk', dec.decode(r.value, {stream: true}));
        }
      }
      push('end', null);
    } catch (e) { push('error', String(e)); }
  })();
  return 1;
})(%s);
"""

# Shows arena's own reCAPTCHA v2 checkbox over the arena.ai page for the human to tick.
# The panel stays below Google's picture popup (z-index 2000000000) and is never removed while a check
# runs: removing the checkbox orphans the popup, and Verify then does nothing.
_CHECK_JS = r"""
(function (v2key, action) {
  if (document.getElementById('arena-desktop-check')) return 1;
  var box = document.createElement('div');
  box.id = 'arena-desktop-check';
  box.style.cssText = 'position:fixed;inset:0;z-index:1999999999;background:rgba(20,20,19,.88);' +
    'display:flex;align-items:center;justify-content:center;font:14px system-ui,sans-serif;color:#F4F0EB';
  box.innerHTML = '<div style="background:#2C2B28;padding:24px 28px;border-radius:12px;max-width:440px;text-align:center">' +
    '<h3 style="margin:0 0 8px;font-size:18px">Quick human check</h3>' +
    '<p style="margin:0 0 16px;opacity:.8">arena.ai asked for verification before sending your message. ' +
    'Tick the box. Arena Desktop resends your message when you are done.</p>' +
    '<div id="arena-desktop-v2" style="display:inline-block;min-height:78px"></div>' +
    '<p style="margin:14px 0 0;opacity:.6;font-size:12px">If pictures appear, pick them and press Verify. ' +
    'This pane closes by itself once arena.ai accepts the check.</p></div>';
  document.body.appendChild(box);
  if (!window.grecaptcha) {
    var s = document.createElement('script');
    s.src = 'https://www.google.com/recaptcha/enterprise.js?render=explicit';
    document.head.appendChild(s);
  }
  var tries = 0;
  (function render() {
    var g = window.grecaptcha && (window.grecaptcha.enterprise || window.grecaptcha);
    if (!g || !g.render) { if (++tries < 60) setTimeout(render, 250); return; }
    g.ready(function () {
      try {
        g.render('arena-desktop-v2', {sitekey: v2key, action: action, theme: 'dark',
          callback: function (t) { window.pywebview.api.challenge_solved(t); box.remove(); }});
      } catch (e) { document.getElementById('arena-desktop-v2').textContent = 'Checkbox unavailable: ' + e; }
    });
  })();
  return 1;
})(%s);
"""

_KEY_JS = ("(function(){var t=document.querySelector('script[src*=\"recaptcha\"][src*=\"render=\"]');"
           "return t?new URL(t.src).searchParams.get('render'):null})()")


class _Bridge:
    """js_api of the engine window. arena.ai's page can call only these two methods."""

    def __init__(self, engine):
        self._engine = engine

    def push(self, rid, seq, kind, data):
        self._engine._deliver(rid, seq, kind, data)

    def challenge_solved(self, token):
        self._engine._on_v2(token)


class EngineResponse:
    """Duck-types the parts of requests.Response the app uses."""

    def __init__(self, engine, rid: str, q: "queue.Queue", timeout: float):
        self._engine, self._rid, self._q, self._timeout = engine, rid, q, timeout
        self._done = False
        self.error: Optional[str] = None
        kind, data = self._next(min(timeout, 90))
        if kind == "status":
            self.status_code = int(data)
        else:
            self.status_code = 0
            self.error = str(data)
            self._finish()

    def _next(self, timeout=None):
        try:
            return self._q.get(timeout=timeout or self._timeout)
        except queue.Empty:
            return ("error", "timed out waiting for arena.ai")

    def _finish(self):
        self._done = True
        self._engine._close(self._rid)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def iter_text(self):
        while not self._done:
            kind, data = self._next()
            if kind == "chunk":
                yield str(data)
            else:
                if kind == "error":
                    self.error = str(data)
                self._finish()

    def iter_content(self, chunk_size=None):
        for text in self.iter_text():
            yield text.encode("utf-8")

    @property
    def text(self) -> str:
        if not hasattr(self, "_text"):
            self._text = "".join(self.iter_text())
        return self._text

    def json(self):
        return json.loads(self.text)


class BrowserEngine:
    def __init__(self):
        self.window = None
        self.loaded = False
        self.host = ""
        self.challenge: Optional[str] = None  # None | "recaptcha" | "cloudflare"
        self.v2_token: Optional[str] = None
        self.login_open = False
        self._streams: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._imported = False

    def bridge(self) -> _Bridge:
        return _Bridge(self)

    def attach(self, window, main=None):
        self.window = window
        self.main = main
        window.events.loaded += lambda *a: threading.Thread(target=self._after_load, daemon=True).start()
        window.events.closing += self._on_closing

    def ready(self) -> bool:
        return self.window is not None and self.loaded

    def wait_ready(self, timeout: float = 30.0) -> bool:
        end = time.time() + timeout
        while time.time() < end and not self.ready():
            time.sleep(0.25)
        return self.ready()

    def state(self) -> dict:
        return {"attached": self.window is not None, "ready": self.ready(), "challenge": self.challenge,
                "host": self.host, "login_open": self.login_open}

    # -- window lifecycle -------------------------------------------------
    def _on_closing(self, *a):
        # Closing the window only hides it; the engine keeps running.
        self.close_pane()
        return False

    def close_pane(self):
        """The user closed the arena.ai pane: drop any open check or sign-in and hide it."""
        if self.challenge == "recaptcha":
            self.challenge = None
        self.login_open = False
        threading.Thread(target=self.hide, daemon=True).start()


    def _retry_initial_load(self):
        time.sleep(2)
        if self.window and not self.host.endswith("arena.ai") and not self.login_open:
            try:
                self.window.load_url(contracts.ORIGIN)
            except Exception:
                pass

    def _after_load(self):
        try:
            title = str(self.window.evaluate_js("document.title") or "")
            self.host = str(self.window.evaluate_js("location.host") or "")
        except Exception:
            title = ""
        if "just a moment" in title.lower():
            self.loaded = False
            self.challenge = "cloudflare"
            self._present()
            return
        if not self.host.endswith("arena.ai"):
            self.loaded = False  # e.g. Google's sign-in page during login
            if self.host in ("chromewebdata", ""):
                threading.Thread(target=self._retry_initial_load, daemon=True).start()
            return
        if self.challenge == "cloudflare":
            self.challenge = None
            if not self.login_open:
                self.hide()
        if not self._imported and not self.has_session():
            self._imported = True
            from arena.config import COOKIE_FILE
            try:
                saved = COOKIE_FILE.read_text(encoding="utf-8").strip()
            except OSError:
                saved = ""
            if contracts.AUTH_COOKIE_PREFIX in saved and self.import_cookies(saved):
                return  # reloads; this handler runs again
        self._imported = True
        self.loaded = True

    def _present(self):
        """Show the arena.ai page: as a pane inside the app window when docking works, else over it."""
        dock = getattr(self, "dock", None)
        if dock is not None and dock.show():
            return
        w, m = self.window, getattr(self, "main", None)
        spot = None
        if m is not None:
            try:
                spot = (int(m.x) + 40, int(m.y) + 40)
                w.resize(max(int(m.width) - 80, 720), max(int(m.height) - 80, 560))
                w.move(*spot)
            except Exception:
                spot = None
        w.show()
        if spot:
            try:
                w.move(*spot)  # the first show() can re-center the window on screen
            except Exception:
                pass

    def show(self):
        if self.window:
            self._present()

    def hide(self):
        dock = getattr(self, "dock", None)
        if dock is not None and dock.visible:
            dock.hide()
        elif self.window:
            self.window.hide()

    def open_login(self):
        self.login_open = True
        self._present()
        if not self.host.endswith("arena.ai"):
            self.window.load_url(contracts.ORIGIN)

    def finish_login(self):
        self.login_open = False
        self.hide()

    def show_cloudflare(self):
        self.loaded = False
        self.challenge = "cloudflare"
        self.window.load_url(contracts.ORIGIN)
        self._present()

    def page_site_key(self) -> Optional[str]:
        try:
            key = self.window.evaluate_js(_KEY_JS)
        except Exception:
            return None
        return key if isinstance(key, str) and contracts.SITE_KEY_RE.fullmatch(key) else None

    # -- cookies ----------------------------------------------------------
    def cookies(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        try:
            for jar in self.window.get_cookies() or []:
                for name, morsel in jar.items():
                    domain = (morsel.get("domain") or "arena.ai").lstrip(".")
                    if domain.endswith("arena.ai"):
                        out[name] = morsel.value
        except Exception:
            pass
        return out

    def has_session(self) -> bool:
        return any(k.startswith(contracts.AUTH_COOKIE_PREFIX) for k in self.cookies())

    def import_cookies(self, cookie_str: str) -> bool:
        """Copy auth cookies into the engine, drop stale auth chunks, then reload arena.ai.

        arena's Supabase SSR cookies are not HttpOnly, so document.cookie can set them.
        """
        pairs = [p.strip() for p in (cookie_str or "").split(";")
                 if "=" in p and p.strip().startswith(contracts.AUTH_COOKIE_PREFIX)]
        if not pairs or not self.window:
            return False
        if not self.host.endswith("arena.ai"):
            self.window.load_url(contracts.ORIGIN)
            end = time.time() + 20
            while time.time() < end and not self.host.endswith("arena.ai"):
                time.sleep(0.25)
        names = [p.split("=", 1)[0] for p in pairs]
        js = ("(function(keep,pairs,prefix){document.cookie.split(';').forEach(function(c){"
              "var n=c.split('=')[0].trim();if(n.indexOf(prefix)===0&&keep.indexOf(n)<0)"
              "document.cookie=n+'=; path=/; max-age=0; secure';});"
              "pairs.forEach(function(p){document.cookie=p+'; path=/; max-age=34560000; secure; samesite=lax';});"
              "location.reload();return 1})(%s,%s,%s)") % (
            json.dumps(names), json.dumps(pairs), json.dumps(contracts.AUTH_COOKIE_PREFIX))
        self._imported = True
        self.loaded = False
        self.window.evaluate_js(js)
        return True

    def sync_to(self, client):
        """The engine owns the refresh-token family: copy its rotated auth cookies back to the app."""
        auth = {k: v for k, v in self.cookies().items() if k.startswith(contracts.AUTH_COOKIE_PREFIX)}
        if not auth:
            return
        cookie_str = "; ".join(f"{k}={v}" for k, v in sorted(auth.items()))
        if cookie_str != client.cookie_str:
            client.set_cookie(cookie_str)
            from arena.config import save_cookie
            save_cookie(cookie_str)

    def logout(self):
        if not self.window:
            return
        self._imported = True
        self.loaded = False
        js = ("(async function(){try{await fetch(%s,{method:'POST',credentials:'include'})}catch(e){}"
              "document.cookie.split(';').forEach(function(c){var n=c.split('=')[0].trim();"
              "if(n.indexOf(%s)===0)document.cookie=n+'=; path=/; max-age=0; secure';});location.reload()})();1"
              ) % (json.dumps(contracts.PATHS["sign_out"]), json.dumps(contracts.AUTH_COOKIE_PREFIX))
        try:
            self.window.evaluate_js(js)
        except Exception:
            pass

    # -- requests ---------------------------------------------------------
    def request(self, path: str, body=None, method: Optional[str] = None, timeout: float = 180) -> EngineResponse:
        """Run fetch() inside arena.ai's page; returns once the status line arrives."""
        rid = uuid.uuid4().hex
        q: "queue.Queue" = queue.Queue()
        with self._lock:
            self._streams[rid] = {"q": q, "next": 0, "held": {}}
        args = ",".join(json.dumps(a) for a in (rid, path, method or ("POST" if body is not None else "GET"),
                                               body, contracts.KEYS["v3"], contracts.RECAPTCHA_ACTION))
        run = getattr(self.window, "run_js", None) or self.window.evaluate_js
        try:
            run(_FETCH_JS % args)
        except Exception as e:
            self._deliver(rid, 0, "error", f"engine script failed: {e}")
        return EngineResponse(self, rid, q, timeout)

    def get_me(self, timeout: float = 25) -> Tuple[Optional[dict], Optional[str]]:
        if not self.wait_ready(timeout):
            return None, (f"arena.ai is waiting for a {self.challenge} check" if self.challenge
                          else "arena.ai window is still loading")
        r = self.request(contracts.PATHS["me"], method="GET", timeout=timeout)
        body = r.text
        if r.status_code == 0:
            return None, f"Network error: {r.error}"
        if r.status_code == 200:
            try:
                data = json.loads(body)
            except ValueError:
                return None, "arena.ai sent an unexpected /api/me reply"
            user = data.get("user") if isinstance(data, dict) and "user" in data else data
            if isinstance(user, dict) and (user.get("email") or user.get("id")):
                return user, None
            return None, "Not signed in"
        if r.status_code == 401:
            return None, "Not signed in"
        return None, f"HTTP {r.status_code}"

    def _deliver(self, rid, seq, kind, data):
        with self._lock:
            st = self._streams.get(rid)
            if not st:
                return
            st["held"][int(seq)] = (kind, data)
            while st["next"] in st["held"]:
                st["q"].put(st["held"].pop(st["next"]))
                st["next"] += 1

    def _close(self, rid):
        with self._lock:
            self._streams.pop(rid, None)

    # -- human verification -----------------------------------------------
    def request_human_check(self):
        """Show arena.ai with its reCAPTCHA v2 checkbox; the token lands in self.v2_token."""
        if not self.window:
            return
        self.v2_token = None
        self.challenge = "recaptcha"
        LOG.info("arena.ai asked for a human check")
        self._present()
        self.window.evaluate_js(_CHECK_JS % ",".join(json.dumps(a) for a in (contracts.KEYS["v2"], contracts.RECAPTCHA_ACTION)))

    def cancel_check(self):
        self.challenge = None
        try:
            self.window.evaluate_js("(function(){var b=document.getElementById('arena-desktop-check');if(b)b.remove();return 1})()")
        except Exception:
            pass
        if not self.login_open:
            threading.Thread(target=self.hide, daemon=True).start()

    def _on_v2(self, token):
        self.v2_token = str(token or "") or None
        LOG.info("human check finished in the page, token %s", "received" if self.v2_token else "empty")
        self.challenge = None
        if not self.login_open:
            threading.Thread(target=self.hide, daemon=True).start()

    def take_v2_token(self) -> Optional[str]:
        token, self.v2_token = self.v2_token, None
        return token


ENGINE = BrowserEngine()
