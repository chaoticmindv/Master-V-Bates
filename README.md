<p align="center">
<img src="assets/logo.png" alt="Arena Desktop logo" width="96px"/>
</p>

<h1 align="center"><b>Arena Desktop</b></h1>

<p align="center"><b>An unofficial desktop app for arena.ai. Chat with 400+ AI models, battle them, and let them work on the files on your PC.</b><br/>One window, like Claude Desktop: arena.ai runs inside the app.</p>

<p align="center">
  <a href="https://github.com/PlayzAe/arena.ai-desktop/releases/latest">Download</a> |
  <a href="https://arena.ai">arena.ai</a> |
  <a href="https://github.com/PlayzAe/arena.ai-desktop/issues">Report a bug</a> |
  <a href="#help-wanted-macos-and-linux">Help wanted</a>
</p>

<div align="center">
  <a href="https://github.com/PlayzAe/arena.ai-desktop/stargazers"><img src="https://img.shields.io/github/stars/PlayzAe/arena.ai-desktop?style=flat-square&color=crimson" alt="GitHub stars" /></a>
  <a href="https://github.com/PlayzAe/arena.ai-desktop/releases/latest"><img src="https://img.shields.io/github/v/release/PlayzAe/arena.ai-desktop?style=flat-square" alt="Latest release" /></a>
  <img src="https://img.shields.io/badge/models-400%2B-10B981?style=flat-square" alt="400+ models" />
  <img src="https://img.shields.io/badge/Platform-Windows-blue?style=flat-square" alt="Platform" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="MIT license" /></a>
</div>

<h5 align="center">Leave a star if you like the project.</h5>

> [!NOTE]
> Arena Desktop runs on **Windows** today. **I'm looking for people to help me** bring it to macOS and Linux and make it better: see [Help wanted](#help-wanted-macos-and-linux).

> [!IMPORTANT]
> This is an unofficial, community-built app. It is not affiliated with or endorsed by Arena AI Inc. You sign in with your own arena.ai account, and you are responsible for following arena.ai's terms. The app never solves human checks for you: when arena.ai asks for one, you tick it yourself.

---

## Contents

- [Download](#download)
- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Repository layout](#repository-layout)
- [Build, run and test](#build-run-and-test)
- [Troubleshooting](#troubleshooting)
- [Help wanted: macOS and Linux](#help-wanted-macos-and-linux)

## Download

Every build is on the [releases page](https://github.com/PlayzAe/arena.ai-desktop/releases/latest).

| Platform | File | Notes |
| --- | --- | --- |
| Windows 10 / 11 | `arena-ai.exe` | One file, runs without installing. Needs the Microsoft Edge WebView2 runtime (built into Windows 11). |

**Windows:** SmartScreen may warn that the app is unrecognised. Click **More info → Run anyway**.

## What it does

**Chat**

- **Four modes:** Battle (two anonymous models, you vote A, B, tie or both bad), Direct (one model you pick), Side by Side (two models you pick) and Agent.
- **Every modality:** Text, Code, Image, Video and Search, with model names on every reply.
- **Chats you can reopen:** each chat keeps its own history and arena.ai conversation. A Stop button that really stops, and a thinking state while a model works.
- **Multiple accounts:** click the account row at the bottom of the sidebar to add, switch or sign out of arena.ai accounts. Chats are kept per account.
- **Live model list:** the picker refreshes from arena.ai's catalog, so new models appear and removed ones drop out without restarting.

**Your files**

- **Pick a folder in the chat box** and every text chat can use it, whatever the mode: the model can list, read, search, create, edit and delete files there and run commands.
- **Battle and Side by Side** give each model its own copy of the folder (`option-a`, `option-b`), so two models never overwrite each other.
- **Permission modes** like Claude Code: Ask every time, Accept edits, Auto, Plan (read only) and Bypass.
- **Change cards:** every file change shows as a card with `+added -removed` lines and a **Show changes** dropdown with the diff.
- **Images and videos** you generate are saved into the picked folder.
- **Code mode** (work in progress): arena.ai builds the project in its own sandbox; Arena Desktop copies the files into your folder and shows the preview link.

**The app**

- **One window.** arena.ai runs in a pane inside the app (the globe button opens it), like the built-in browser in Claude Desktop. Sign in there once.
- **Slash commands** (`/`) in the chat box, a simple settings page, a docs page (F1), and loading states when the app opens and closes.

## How it works

1. The app starts a small local web UI (Flask) in a [pywebview](https://pywebview.flowrl.com/) window, plus a hidden arena.ai page in a second WebView2 view that is docked into the same window.
2. You sign in to arena.ai in that pane. The app uses that session; your password never passes through the app.
3. Each message is sent from inside the arena.ai page, the same way arena.ai's own site sends it, and the answer is streamed back into the app.
4. When a folder is picked, the app gives the model a short guide to its file tools. The model writes tool tags in its reply, the app runs them under your permission mode, and sends the results back.
5. If arena.ai asks for a human check, the pane opens so you can tick it, and your message is resent after.

## Repository layout

```
arena.ai-desktop/
├─ arena/
│  ├─ desktop.py       Desktop app: windows, docking the arena.ai pane, startup and close
│  ├─ engine.py        The arena.ai page: sending, streaming, human checks
│  ├─ web/             Local UI: app.py (Flask API) and static/ (HTML, CSS, JS)
│  ├─ agent.py         File tools for the models (ls, read, search, write, edit, run)
│  ├─ permissions.py   Permission modes
│  ├─ contracts.py     arena.ai request and stream formats
│  ├─ workspace.py     Project folders for Code mode
│  └─ cli.py           Optional command-line version
├─ tests/              Test suite (pytest)
├─ assets/             Logo and icon
├─ arena-cli.spec      PyInstaller build for arena-ai.exe
└─ requirements.txt
```

## Build, run and test

You need Python 3.11+ and Windows 10/11.

```bash
pip install -r requirements.txt
python -m arena.desktop                    # run the desktop app from source
python -m pytest -q tests                  # run the tests
pip install pyinstaller
python -m PyInstaller --noconfirm arena-cli.spec   # builds dist/arena-ai.exe
```

The command-line version still works: `python arena-cli.py` or `arena.bat chat`.

## Troubleshooting

- **App log:** `%USERPROFILE%\.arena-cli\desktop.log` records each send, its HTTP status and human checks. Attach it to bug reports.
- **Raw stream dump:** start the app with `ARENA_STREAM_DUMP=1` to save every line arena.ai streams to `%USERPROFILE%\.arena-cli\streams\`.
- **Signed out:** open the arena.ai pane with the globe button and sign in again.

## Help wanted: macOS and Linux

Arena Desktop is a passion project of mine. Right now it runs on **Windows**, and **I'm looking for people to help me**.

I'd love help with:

- **macOS and Linux:** pywebview already runs on Cocoa, GTK and Qt, so most of the work is the arena.ai pane. On Windows it is docked into the main window with Win32 `SetParent` (`arena/desktop.py`, class `Dock`); other systems need their own way to do this, plus packaging and testing.
- **Code mode:** copying everything arena.ai's sandbox builds into your folder, live, for both models in a battle.
- **Bugs and polish:** anything that breaks, looks off or could be faster.

If you can help, please **fork the repo and open a pull request**, or open an issue to talk about it first. Found a bug? Open an issue with your `desktop.log`, or a pull request if you know the fix. Testing on your own machine, ideas and small fixes are all welcome too. Thank you!

---

<p align="center"><sub>Made with care by <a href="https://github.com/PlayzAe">PlayzAe</a>. MIT licensed.</sub></p>
