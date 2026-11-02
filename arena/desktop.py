"""
Arena Desktop: a native window (pywebview + Edge WebView2) over the local Flask
UI, plus a hidden arena.ai window (the engine) that sends chats from arena's
own page. Sign-in and human checks show it as a pane inside the main window.
"""

import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def choose_desktop_port() -> int:
    env_port = int(os.environ.get("ARENA_PORT") or 0)
    if env_port > 0:
        return env_port
    for p in range(8080, 8095):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return find_free_port()


def start_flask(port: int):
    from arena.web.app import app
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True, use_reloader=False)


def wait_port(port: int, timeout: float = 10.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return True
        except OSError:
            time.sleep(0.1)
    return False


def _dialog(name: str):
    import webview
    fd = getattr(webview, "FileDialog", None)
    if fd is not None:
        return getattr(fd, name)
    return getattr(webview, f"{name}_DIALOG")


class JsBridge:
    """js_api of the main window (local UI only). pywebview exposes every public attribute to JS
    and walks it recursively, so the window reference must stay private."""

    def __init__(self):
        self._window = None
        self._titlebar = None

    def open_file_dialog(self, file_types=None):
        ft = tuple(file_types or ()) + ("All files (*.*)",)
        result = self._window.create_file_dialog(_dialog("OPEN"), allow_multiple=True, file_types=ft)
        return list(result or [])

    def save_file_dialog(self, filename=""):
        result = self._window.create_file_dialog(_dialog("SAVE"), save_filename=filename)
        if isinstance(result, (list, tuple)):
            result = result[0] if result else None
        return result or None

    def choose_folder(self):
        result = self._window.create_file_dialog(_dialog("FOLDER"))
        return (result[0] if result else None) if isinstance(result, (list, tuple)) else result

    # ── custom title bar (the window is frameless) ──
    def tb_minimize(self):
        if self._titlebar:
            self._titlebar.minimize()

    def tb_toggle_maximize(self):
        if self._titlebar:
            self._titlebar.toggle_maximize()

    def tb_close(self):
        if self._titlebar:
            self._titlebar.close()


def _user32():
    import ctypes
    from ctypes import wintypes as w
    u = ctypes.WinDLL("user32")  # own instance: argtypes set here do not leak into other ctypes users
    u.EnumProc = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    u.EnumWindows.argtypes = [u.EnumProc, w.LPARAM]
    u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    u.GetWindowLongW.argtypes = [w.HWND, ctypes.c_int]
    u.SetWindowLongW.argtypes = [w.HWND, ctypes.c_int, ctypes.c_long]
    u.SetParent.argtypes = [w.HWND, w.HWND]
    u.SetParent.restype = w.HWND
    u.ShowWindowAsync.argtypes = [w.HWND, ctypes.c_int]
    u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT]
    return u


class TitleBar:
    """Custom title bar for the frameless window: the page draws drag space and
    min/max/close buttons (like VS Code), and calls back into this class."""

    def __init__(self):
        self._window = None
        self._maximized = False

    def bind(self, window):
        self._window = window

    def notify(self):
        if self._window:
            self._window.evaluate_js("window.titlebarState && titlebarState(%s)" % ("true" if self._maximized else "false"))

    def on_maximized(self, state: bool):
        self._maximized = state
        self.notify()

    def minimize(self):
        try:
            self._window.minimize()
        except Exception:
            logging.getLogger("arena.desktop").exception("titlebar minimize failed")

    def toggle_maximize(self):
        try:
            if self._maximized:
                self._window.restore()
            else:
                self._window.maximize()
        except Exception:
            logging.getLogger("arena.desktop").exception("titlebar toggle_maximize failed")

    def close(self):
        try:
            self._window.destroy()
        except Exception:
            logging.getLogger("arena.desktop").exception("titlebar close failed")


class Dock:
    """Hosts the arena.ai window as a pane on the right of the main window (Win32 SetParent),
    like a built-in browser, so sign-in and human checks never open a second window."""

    SHARE = 0.55  # part of the main window's width the pane takes

    def __init__(self, main_win, pane_win):
        self.main, self.pane = main_win, pane_win
        self.h_main = self.h_pane = None
        self.visible = False
        self._share = None
        self._closing = False
        self.u = _user32()

    def _find(self, title):
        import ctypes
        from ctypes import wintypes
        found, pid = [], os.getpid()

        def each(h, _):
            owner = wintypes.DWORD()
            self.u.GetWindowThreadProcessId(h, ctypes.byref(owner))
            buf = ctypes.create_unicode_buffer(256)
            self.u.GetWindowTextW(h, buf, 256)
            if owner.value == pid and buf.value == title:
                found.append(h)
            return True

        self.u.EnumWindows(self.u.EnumProc(each), 0)
        return found[0] if found else None

    def _embed(self) -> bool:
        if self.h_pane:
            return True
        self.h_main = self.h_main or self._find(self.main.title)
        pane = self._find(self.pane.title)
        if not (self.h_main and pane):
            return False
        style = self.u.GetWindowLongW(pane, -16) & 0xFFFFFFFF  # GWL_STYLE
        style &= ~(0x80000000 | 0x00C00000 | 0x00040000 | 0x00080000 | 0x00020000 | 0x00010000)  # popup, caption, frame, buttons
        style |= 0x40000000 | 0x04000000  # WS_CHILD | WS_CLIPSIBLINGS
        self.u.SetWindowLongW(pane, -16, style - (1 << 32) if style >= 1 << 31 else style)
        self.u.SetParent(pane, self.h_main)
        self.h_pane = pane
        return True

    def layout(self):
        if not (self.visible and self.h_pane):
            return
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        self.u.GetClientRect(self.h_main, ctypes.byref(r))
        w, h = r.right, r.bottom
        pw = min(w, max(int(w * self.SHARE), 560))
        self.u.SetWindowPos(self.h_pane, None, w - pw, 0, pw, h, 0x0040 | 0x0020)  # HWND_TOP, SWP_SHOWWINDOW | SWP_FRAMECHANGED
        share = round(pw / max(w, 1), 4)
        if share != self._share:  # resizing fires often: only tell the page when the split changes
            self._share = share
            self.main.evaluate_js("window.arenaPane && arenaPane(true, %.4f)" % share)

    def prime(self):
        """Find the main window handle early: the closing handler must not send window messages."""
        if not self.h_main:
            self.h_main = self._find(self.main.title)

    def vanish(self):
        """Close in two steps: hide the window at once, then tear WebView2 down out of sight.
        pywebview runs this on a worker while the GUI thread waits, so the work happens on a new thread."""
        if self._closing:
            return None
        self._closing = True
        threading.Thread(target=self._quit, daemon=True).start()
        return False  # cancel this close; _quit closes for real

    def _quit(self):
        try:
            self.main.hide()
        finally:
            self.main.destroy()

    def show(self) -> bool:
        try:
            if not self._embed():
                return False
            self.visible = True
            self.pane.show()
            self.layout()
            return True
        except Exception:
            logging.getLogger("arena.desktop").exception("could not dock the arena.ai pane")
            self.visible = False
            return False

    def hide(self):
        self.visible = False
        self._share = None
        self.pane.hide()
        try:
            self.main.evaluate_js("window.arenaPane && arenaPane(false)")
        except Exception:
            pass


def main():
    import webview
    from arena import contracts
    from arena.config import CONFIG_DIR
    from arena.engine import ENGINE

    contracts.load_overrides()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(CONFIG_DIR / "desktop.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # keep the log to what the app does
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("arena.ai.desktop")
        except Exception:
            pass

    port = choose_desktop_port()
    try:
        (CONFIG_DIR / "api_url.txt").write_text(f"http://127.0.0.1:{port}/v1", encoding="utf-8")
    except Exception:
        pass
    threading.Thread(target=start_flask, args=(port,), daemon=True).start()
    wait_port(port)

    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    ico = base / "assets" / "arena-cli.ico"

    webview.settings["ALLOW_DOWNLOADS"] = True  # zip and media downloads from the UI
    bridge = JsBridge()
    # Frameless window with a page-drawn title bar (drag space + min/max/close), like VS Code,
    # so the app owns the whole window height. easy_drag off: the drag area is our own.
    main_win = webview.create_window("Arena Desktop", f"http://127.0.0.1:{port}", width=1280, height=840,
                                     min_size=(860, 600), background_color="#242422", text_select=True, js_api=bridge,
                                     frameless=True, easy_drag=False)
    bridge._window = main_win
    titlebar = TitleBar()
    titlebar.bind(main_win)
    bridge._titlebar = titlebar
    main_win.events.maximized += lambda *a: titlebar.on_maximized(True)
    main_win.events.restored += lambda *a: titlebar.on_maximized(False)
    engine_win = webview.create_window("arena.ai - Arena Desktop", contracts.ORIGIN, width=1000, height=760, x=120, y=120,
                                       hidden=True, background_color="#242422", js_api=ENGINE.bridge())
    ENGINE.attach(engine_win, main_win)
    if sys.platform == "win32":
        dock = ENGINE.dock = Dock(main_win, engine_win)
        main_win.events.resized += lambda *a: dock.layout()
        main_win.events.loaded += lambda *a: dock.prime()
        main_win.events.closing += lambda *a: dock.vanish()
    main_win.events.closed += lambda *a: os._exit(0)

    storage = CONFIG_DIR / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    webview.start(gui="edgechromium", private_mode=False, storage_path=str(storage),
                  icon=str(ico) if ico.exists() else None, debug=bool(os.environ.get("ARENA_DEBUG")))
    os._exit(0)


if __name__ == "__main__":
    main()
