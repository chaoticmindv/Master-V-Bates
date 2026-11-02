"""
Arena.ai client and streaming response parser.
Supports all 4 modalities: Text/Chat, Code/Webdev (with sandbox preview deployments),
Search (with source citations), and Image Generation.
"""

import base64
import json
import os
import re
import threading
import time
import uuid
from typing import Dict, Any, Generator, Tuple, Optional, List

import requests

from arena.console import con
from arena.config import BASE_URL, API_PREFIX

STREAM_TYPES = {
    "0": "text",
    "2": "data",
    "3": "error",
    "d": "finish_message",
    "e": "finish_step",
    "g": "reasoning",
    "h": "source",
}

RECAPTCHA_SITE_KEY = "6LeTGMcsAAAAALuIlkVwIxaAuZA8VledA6d3Nnb0"
RECAPTCHA_CO = base64.b64encode(b"https://arena.ai:443").decode().rstrip("=")


def _cdp_find_arena_tab(port: int = 9222) -> Optional[str]:
    """Find an arena.ai tab's WebSocket debugger URL via CDP."""
    import http.client
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/json")
        resp = conn.getresponse()
        if resp.status != 200:
            return None
        pages = json.loads(resp.read().decode("utf-8"))
        conn.close()
        for p in pages:
            if "arena.ai" in p.get("url", ""):
                return p.get("webSocketDebuggerUrl")
        # No arena tab found — try any tab and navigate it
        for p in pages:
            ws = p.get("webSocketDebuggerUrl")
            if ws and p.get("type") == "page":
                return ws
        return None
    except Exception:
        return None


def _cdp_ensure_arena_page(port: int = 9222) -> Optional[str]:
    """Ensure the CDP tab is on arena.ai (navigate if needed). Returns ws_url."""
    import http.client
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/json")
        resp = conn.getresponse()
        if resp.status != 200:
            return None
        pages = json.loads(resp.read().decode("utf-8"))
        conn.close()

        # Check for existing arena tab
        for p in pages:
            if "arena.ai" in p.get("url", ""):
                return p.get("webSocketDebuggerUrl")

        # Navigate first available page tab to arena.ai
        for p in pages:
            ws = p.get("webSocketDebuggerUrl")
            if ws and p.get("type") == "page":
                _cdp_execute(ws, "Page.navigate", {"url": "https://arena.ai"})
                time.sleep(3)
                return ws
        return None
    except Exception:
        return None


def _cdp_execute(ws_url: str, method: str, params: dict = None, timeout: int = 10) -> Optional[dict]:
    """Execute a CDP command and return the result."""
    try:
        import websocket
        ws = websocket.create_connection(ws_url, timeout=timeout)
        msg = {"id": 1, "method": method}
        if params:
            msg["params"] = params
        ws.send(json.dumps(msg))
        result = json.loads(ws.recv())
        ws.close()
        return result
    except Exception:
        return None


def fetch_recaptcha_via_cdp(action: str = "chat_submit", port: int = 9222) -> Optional[str]:
    """Get a fresh reCAPTCHA Enterprise token by executing grecaptcha in a real browser tab."""
    ws_url = _cdp_ensure_arena_page(port)
    if not ws_url:
        return None

    js = f"""
    (async () => {{
        // Wait for grecaptcha to load (up to 8s)
        for (let i = 0; i < 16; i++) {{
            if (typeof grecaptcha !== 'undefined' && grecaptcha.enterprise) break;
            await new Promise(r => setTimeout(r, 500));
        }}
        if (typeof grecaptcha === 'undefined' || !grecaptcha.enterprise) {{
            return {{error: 'grecaptcha not loaded — page may not be arena.ai'}};
        }}
        try {{
            const token = await grecaptcha.enterprise.execute('{RECAPTCHA_SITE_KEY}', {{action: '{action}'}});
            return {{token: token}};
        }} catch(e) {{
            return {{error: 'reCAPTCHA execute failed: ' + e.message}};
        }}
    }})()
    """
    result = _cdp_execute(ws_url, "Runtime.evaluate", {
        "expression": js,
        "returnByValue": True,
        "awaitPromise": True,
    }, timeout=15)
    if result:
        val = result.get("result", {}).get("result", {}).get("value")
        if isinstance(val, dict):
            tok = val.get("token")
            if tok and isinstance(tok, str) and len(tok) > 20:
                return tok
        elif isinstance(val, str) and len(val) > 20:
            return val
    return None


def fetch_cookies_via_cdp(port: int = 9222) -> Optional[str]:
    """Get ALL cookies for arena.ai (including httpOnly) via CDP Network.getAllCookies."""
    ws_url = _cdp_find_arena_tab(port)
    if not ws_url:
        return None

    result = _cdp_execute(ws_url, "Network.getAllCookies")
    if not result:
        return None

    cookies = result.get("result", {}).get("cookies", [])
    arena_cookies = [c for c in cookies if "arena.ai" in c.get("domain", "")]
    if not arena_cookies:
        return None

    return "; ".join(f"{c['name']}={c['value']}" for c in arena_cookies)


def inject_cookies_via_cdp(cookie_str: str, port: int = 9222) -> bool:
    """Inject auth cookies into the CDP browser so API requests go through authenticated."""
    ws_url = _cdp_find_arena_tab(port)
    if not ws_url:
        return False

    cookies = {}
    for part in cookie_str.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            cookies[k.strip()] = v.strip()

    # Inject each auth cookie
    for name, value in cookies.items():
        if not name.startswith("arena-auth"):
            continue
        _cdp_execute(ws_url, "Network.setCookie", {
            "name": name,
            "value": value,
            "domain": ".arena.ai",
            "path": "/",
            "secure": True,
            "httpOnly": True,
        }, timeout=5)

    # Verify by checking if arena-auth-prod-v1.0 is now present
    result = _cdp_execute(ws_url, "Network.getAllCookies")
    if result:
        all_cookies = result.get("result", {}).get("cookies", [])
        for c in all_cookies:
            if c.get("name") == "arena-auth-prod-v1.0":
                return True
    return False


def send_chat_via_cdp(
    model_id: str,
    message: str,
    eval_id: Optional[str] = None,
    modality: str = "chat",
    port: int = 9222,
    timeout: int = 60,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Send chat entirely through browser CDP. Returns (text, eval_id, error).
    The browser handles reCAPTCHA + all cookies automatically.
    """
    ws_url = _cdp_ensure_arena_page(port)
    if not ws_url:
        return None, eval_id, "No CDP browser found. Run /login to launch one, or start your browser with --remote-debugging-port=9222"

    is_new = eval_id is None
    js_eval_id = f"'{eval_id}'" if eval_id else "null"

    js = f"""
    (async () => {{
        function uuidv7() {{
            const ms = Date.now();
            const b = new Uint8Array(16);
            const msBytes = [];
            let tmp = ms;
            for(let i=5;i>=0;i--) {{ msBytes[i]=tmp&0xFF; tmp=Math.floor(tmp/256); }}
            for(let i=0;i<6;i++) b[i]=msBytes[i];
            crypto.getRandomValues(b.subarray(6));
            b[6]=(b[6]&0x0F)|0x70;
            b[8]=(b[8]&0x3F)|0x80;
            const h=[...b].map(x=>x.toString(16).padStart(2,'0')).join('');
            return h.slice(0,8)+'-'+h.slice(8,12)+'-'+h.slice(12,16)+'-'+h.slice(16,20)+'-'+h.slice(20);
        }}

        const SITE_KEY = '{RECAPTCHA_SITE_KEY}';
        let token = null;
        try {{
            if (typeof grecaptcha !== 'undefined' && grecaptcha.enterprise) {{
                token = await grecaptcha.enterprise.execute(SITE_KEY, {{action: 'chat_submit'}});
            }}
        }} catch(e) {{}}

        const evalId = {js_eval_id} || uuidv7();
        const isNew = {str(is_new).lower()};
        const url = isNew
            ? '/nextjs-api/stream/create-evaluation'
            : '/nextjs-api/stream/post-to-evaluation/' + evalId;

        const body = {{
            id: evalId,
            mode: '{self.active_mode}',
            userMessageId: uuidv7(),
            modelAMessageId: uuidv7(),
            modelBMessageId: uuidv7(),
            userMessage: {{
                content: {json.dumps(message)},
                experimental_attachments: [],
                metadata: {{}},
            }},
            modality: '{modality}',
            recaptchaV3Token: token,
        }};
        if ('{self.active_mode}' !== 'battle') {{
            body.modelAId = '{model_id}';
        }}

        const resp = await fetch(url, {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify(body),
        }});

        if (!resp.ok) {{
            const err = await resp.text();
            return {{error: `HTTP ${{resp.status}}: ${{err.substring(0, 300)}}`, evalId: evalId}};
        }}

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let text = '';
        let reasoning = '';
        let sources = [];
        let chunks = 0;
        while (true) {{
            const {{done, value}} = await reader.read();
            if (done) break;
            chunks++;
            const chunk = decoder.decode(value, {{stream: true}});
            for (const line of chunk.split('\\n')) {{
                const l = line.trim();
                if (!l) continue;
                if (l.length >= 3 && 'ab'.includes(l[0]) && l[2] === ':') {{
                    if (l[0] === 'a' && l[1] === '0') {{
                        try {{ text += JSON.parse(l.slice(3)); }} catch(e) {{}}
                    }}
                    if (l[0] === 'a' && l[1] === 'g') {{
                        try {{ reasoning += JSON.parse(l.slice(3)); }} catch(e) {{}}
                    }}
                    if (l[0] === 'a' && l[1] === 'h') {{
                        try {{ sources.push(JSON.parse(l.slice(3))); }} catch(e) {{}}
                    }}
                }} else if (l.length >= 2 && l[1] === ':') {{
                    if (l[0] === '0') {{
                        try {{ text += JSON.parse(l.slice(2)); }} catch(e) {{}}
                    }}
                }}
            }}
            if (chunks > 500) break;
        }}

        return {{text, reasoning, sources, evalId, chunks}};
    }})()
    """

    try:
        import websocket
        ws = websocket.create_connection(ws_url, timeout=timeout)
        ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {
                "expression": js,
                "returnByValue": True,
                "awaitPromise": True,
            }
        }))
        raw = json.loads(ws.recv())
        ws.close()
    except Exception as e:
        return None, eval_id, f"CDP connection error: {e}"

    result = raw.get("result", {}).get("result", {}).get("value")
    if not result:
        exc = raw.get("result", {}).get("exceptionDetails", {})
        if exc:
            return None, eval_id, f"Browser JS error: {exc.get('text', str(exc)[:200])}"
        return None, eval_id, "Empty response from browser"

    if isinstance(result, dict):
        if result.get("error"):
            err = result["error"]
            eid = result.get("evalId", eval_id)
            if "403" in err:
                if "captcha" in err.lower() or "recaptcha" in err.lower():
                    return None, eid, "reCAPTCHA rejected — your IP may be temporarily flagged from too many requests. Wait 5-10 minutes, then try again."
                return None, eid, "Session expired or Cloudflare blocked. Run /login to re-authenticate."
            if "429" in err:
                return None, eid, "Rate limited by arena.ai — wait 30-60 seconds before sending another message."
            if "401" in err:
                return None, eid, "Authentication expired. Run /login to refresh your session."
            if "500" in err or "502" in err or "503" in err:
                return None, eid, "Arena.ai server error — the service may be temporarily down. Try again in a minute."
            return None, eid, err
        return result.get("text", ""), result.get("evalId", eval_id), None

    return str(result), eval_id, None


_uuid7_lock = threading.Lock()
_uuid7_last_ms = 0


def generate_uuidv7() -> str:
    """RFC 9562 UUIDv7 with strictly increasing ms: arena rejects message ids not created after the eval id."""
    global _uuid7_last_ms
    with _uuid7_lock:
        ms = max(int(time.time() * 1000), _uuid7_last_ms + 1)
        _uuid7_last_ms = ms
    rand_bytes = os.urandom(10)
    b = ms.to_bytes(6, byteorder="big") + rand_bytes
    b6 = (b[6] & 0x0F) | 0x70
    b8 = (b[8] & 0x3F) | 0x80
    b_final = b[:6] + bytes([b6, b[7], b8]) + b[9:]
    return str(uuid.UUID(bytes=b_final))


def extract_bearer_token(cookie_str: str) -> Optional[str]:
    """Extract Supabase access_token from chunked arena-auth cookies."""
    if not cookie_str:
        return None
    cookies = {}
    for part in cookie_str.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            cookies[k.strip()] = v.strip()

    v0 = cookies.get("arena-auth-prod-v1.0", "")
    v1 = cookies.get("arena-auth-prod-v1.1", "")
    if not v0:
        return None

    try:
        combined = v0.replace("base64-", "") + v1
        combined += "=" * ((4 - len(combined) % 4) % 4)
        decoded = base64.b64decode(combined).decode("utf-8", errors="ignore")
        session_data = json.loads(decoded)
        return session_data.get("access_token")
    except Exception:
        return None


class ArenaClient:
    """Client for interacting with Arena.ai API across all modalities."""

    def __init__(self, cookie_str: Optional[str] = None):
        self.cookie_str = cookie_str
        self.session = requests.Session()
        self._cookie_lock = threading.Lock()
        self.eval_id: Optional[str] = None
        self.active_mode = "battle"
        self.active_modality = "chat"  # 'chat' | 'webdev' | 'search' | 'image'
        self.last_preview_url: Optional[str] = None
        self.sources: List[Dict[str, Any]] = []
        self.cdp_port = 9222
        self.use_cdp = _cdp_find_arena_tab(self.cdp_port) is not None
        if self.use_cdp and cookie_str:
            inject_cookies_via_cdp(cookie_str, self.cdp_port)

        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/",
        })
        self._load_jar(cookie_str)

    def _load_jar(self, cookie_str: Optional[str]) -> None:
        self.session.cookies.clear()
        for part in (cookie_str or "").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k.strip():
                    self.session.cookies.set(k.strip(), v.strip(), domain="arena.ai", path="/")

    def set_cookie(self, cookie_str: str) -> None:
        self.cookie_str = cookie_str
        self._load_jar(cookie_str)

    def sync_cookies(self) -> None:
        """Persist cookies the server rotated. Arena refreshes the Supabase session server-side via
        Set-Cookie; resending the old refresh token after rotation makes Supabase revoke the session."""
        with self._cookie_lock:
            merged: Dict[str, str] = {}
            for c in self.session.cookies:
                if c.domain.lstrip(".").endswith("arena.ai"):
                    merged[c.name] = c.value
            current = "; ".join(f"{k}={v}" for k, v in merged.items())
            if not current or current == self.cookie_str:
                return
            self.cookie_str = current
            self._load_jar(current)
            from arena.config import save_cookie
            save_cookie(current)

    def get_me(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Validate the session against arena.ai (also triggers server-side token refresh)."""
        try:
            r = self.session.get(f"{BASE_URL}/api/me", timeout=20)
        except requests.RequestException as e:
            return None, f"Network error: {e}"
        self.sync_cookies()
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        try:
            user = r.json().get("user")
        except ValueError:
            return None, "Unexpected response from /api/me"
        if not user:
            return None, "Session expired or revoked"
        return user, None

    def send_chat(
        self,
        model_id: str,
        message: str,
        modality: Optional[str] = None,
        attachments: Optional[List[Any]] = None,
        model_b_id: Optional[str] = None,
    ) -> Tuple[Optional[requests.Response], Optional[str]]:
        """
        Send a prompt to Arena.ai for a specific modality.
        Modality can be: 'chat' | 'webdev' | 'search' | 'image' | 'auto'.
        """
        target_modality = modality or self.active_modality
        self.sources.clear()

        is_new_eval = self.eval_id is None
        if is_new_eval:
            self.eval_id = generate_uuidv7()
        user_msg_id = generate_uuidv7()
        model_a_msg_id = generate_uuidv7()

        # Try CDP browser for fresh reCAPTCHA token (works reliably)
        recaptcha_token = fetch_recaptcha_via_cdp("chat_submit")
        if not recaptcha_token:
            con.print("  [dim yellow]No browser CDP for reCAPTCHA - sending without token[/dim yellow]")

        # Only borrow Cloudflare cookies from a CDP browser; mixing its auth cookies would share a refresh-token family
        cdp_cookies = fetch_cookies_via_cdp()
        if cdp_cookies:
            for part in cdp_cookies.split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    if k in ("cf_clearance", "__cf_bm"):
                        self.session.cookies.set(k, v, domain="arena.ai", path="/")

        # First message vs follow-up
        if is_new_eval:
            url = f"{BASE_URL}{API_PREFIX}/stream/create-evaluation"
            body: Dict[str, Any] = {
                "id": self.eval_id,
                "mode": self.active_mode,
                "userMessageId": user_msg_id,
                "modelAMessageId": model_a_msg_id,
                "userMessage": {
                    "content": message,
                    "experimental_attachments": attachments or [],
                    "metadata": {},
                },
                "modality": target_modality,
                "recaptchaV3Token": recaptcha_token,
            }
            if self.active_mode != "battle" and model_id:
                body["modelAId"] = model_id
        else:
            url = f"{BASE_URL}{API_PREFIX}/stream/post-to-evaluation/{self.eval_id}"
            body = {
                "id": self.eval_id,
                "mode": self.active_mode,
                "userMessageId": user_msg_id,
                "modelAMessageId": model_a_msg_id,
                "userMessage": {
                    "content": message,
                    "experimental_attachments": attachments or [],
                    "metadata": {},
                },
                "modality": target_modality,
                "recaptchaV3Token": recaptcha_token,
            }
            if self.active_mode != "battle" and model_id:
                body["modelAId"] = model_id

        # direct-battle rejects a second slot: "Direct chat must start with one model"
        if self.active_mode in ("battle", "side-by-side"):
            body["modelBMessageId"] = generate_uuidv7()
        if model_b_id and self.active_mode == "side-by-side":
            body["modelBId"] = model_b_id

        try:
            resp = self.session.post(url, json=body, stream=True, timeout=180)
        except requests.ConnectionError:
            return None, "Connection failed: check network connection"
        except requests.Timeout:
            return None, "Request timed out (180s)"
        except Exception as e:
            return None, f"Request error: {e}"

        self.sync_cookies()

        if resp.status_code == 401:
            self.eval_id = None
            return None, "Authentication expired. Run /login to refresh your session."

        if resp.status_code == 403:
            err_text = resp.text.lower()
            if "captcha" in err_text:
                return None, ("arena.ai requires a reCAPTCHA token generated by its own page in a real browser; "
                              "this client cannot send chats directly.")
            if "cloudflare" in err_text:
                return None, "Blocked by Cloudflare. Launch a CDP browser via /login for reliable access."
            return None, "Access denied (403). Run /login to re-authenticate."

        if resp.status_code == 429:
            return None, "Rate limited by arena.ai — wait 30-60 seconds before sending another message."

        if not resp.ok:
            self.eval_id = None
            try:
                detail = resp.json()
                if isinstance(detail, dict):
                    detail = detail.get("error", detail.get("message", str(detail)))
            except Exception:
                detail = resp.text[:250]
            if resp.status_code >= 500:
                return None, f"Arena.ai server error ({resp.status_code}). The service may be temporarily down — try again in a minute."
            return None, f"HTTP {resp.status_code}: {detail}"

        return resp, None

    def send_chat_browser(
        self,
        model_id: str,
        message: str,
        modality: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Send chat through CDP browser. Returns (text_response, error)."""
        target_modality = modality or self.active_modality
        text, new_eval_id, err = send_chat_via_cdp(
            model_id=model_id,
            message=message,
            eval_id=self.eval_id,
            modality=target_modality,
            port=self.cdp_port,
        )
        if new_eval_id:
            self.eval_id = new_eval_id
        if err:
            return None, err
        return text, None

    def parse_stream(
        self,
        resp: requests.Response,
        show_reasoning: bool = False,
        debug: bool = False,
    ) -> Generator[Tuple[str, Any], None, None]:
        """
        Parse SSE event stream from Arena.ai.
        Extracts:
        - 'text': Main assistant answer tokens
        - 'source': Search citations and source links (Search modality)
        - 'preview_url': Sandboxed deployment URL (Webdev/code modality)
        - 'image': Generated image URLs (Image modality)
        - 'reasoning': Internal chain-of-thought tokens
        """
        buf = ""
        try:
            for chunk in resp.iter_content(chunk_size=None):
                if not chunk:
                    continue
                buf += chunk.decode("utf-8", errors="replace")
                lines = buf.split("\n")
                buf = lines[-1]

                for line in lines[:-1]:
                    line = line.strip()
                    if not line:
                        continue

                    if debug:
                        con.print(f"  [dim]RAW: {line[:120]}[/dim]")

                    # Format 1: a0:"text" or b0:"text" (Arena Battle format)
                    if len(line) >= 3 and line[0] in "ab" and line[2] == ":":
                        prefix, tc, raw = line[0], line[1], line[3:]
                        if prefix == "b":
                            continue  # Skip Model B in battle mode
                        tn = STREAM_TYPES.get(tc, tc)
                        try:
                            val = json.loads(raw)
                        except Exception:
                            val = raw

                        # Extract preview/deployment URLs & session ID from data events
                        if tn == "data":
                            self._extract_data_metadata(val)
                            # Check if data contains a deployment or preview URL
                            p_url = self._find_preview_url(val)
                            if p_url:
                                self.last_preview_url = p_url
                                yield ("preview_url", p_url)

                        elif tn == "source":
                            # Search citation source
                            self.sources.append(val)
                            yield ("source", val)

                        elif tn == "reasoning":
                            if show_reasoning:
                                yield ("reasoning", val)
                            continue

                        yield (tn, val)
                        continue

                    # Format 2: 0:"text" (standard Vercel AI SDK)
                    if len(line) >= 2 and line[1] == ":":
                        tc, raw = line[0], line[2:]
                        tn = STREAM_TYPES.get(tc, tc)
                        try:
                            val = json.loads(raw)
                        except Exception:
                            val = raw

                        if tn == "data":
                            self._extract_data_metadata(val)
                            p_url = self._find_preview_url(val)
                            if p_url:
                                self.last_preview_url = p_url
                                yield ("preview_url", p_url)
                        elif tn == "source":
                            self.sources.append(val)
                            yield ("source", val)

                        yield (tn, val)
                        continue

                    # Fallback JSON parsing
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            self._extract_data_metadata(obj)
                            p_url = self._find_preview_url(obj)
                            if p_url:
                                self.last_preview_url = p_url
                                yield ("preview_url", p_url)
                            yield ("data", obj)
                    except Exception:
                        pass

        except requests.exceptions.ChunkedEncodingError:
            pass
        except Exception as e:
            if debug:
                con.print(f"  [dim]Stream error: {e}[/dim]")

    def _extract_data_metadata(self, val: Any) -> None:
        """Search nested structures for evaluationSessionId."""
        if isinstance(val, dict):
            eid = val.get("evaluationSessionId") or val.get("id")
            if eid and isinstance(eid, str) and len(eid) > 10:
                self.eval_id = eid
        elif isinstance(val, list):
            for item in val:
                self._extract_data_metadata(item)

    def _find_preview_url(self, val: Any) -> Optional[str]:
        """Detect live web sandbox / preview deployment URLs from model response."""
        if isinstance(val, dict):
            for k in ("sandboxUrl", "previewUrl", "deploymentUrl", "url", "deployUrl", "webUrl"):
                u = val.get(k)
                if u and isinstance(u, str) and ("arena" in u or "preview" in u or "http" in u):
                    return u
            for v in val.values():
                res = self._find_preview_url(v)
                if res:
                    return res
        elif isinstance(val, list):
            for item in val:
                res = self._find_preview_url(item)
                if res:
                    return res
        elif isinstance(val, str):
            match = re.search(r'https?://[a-zA-Z0-9\-\.]+(?:arena\.ai|arena-preview\.ai)[^\s\'"<>]*', val)
            if match:
                return match.group(0)
        return None

    def reset_conversation(self) -> None:
        """Reset conversation session ID."""
        self.eval_id = None
        self.last_preview_url = None
        self.sources.clear()
