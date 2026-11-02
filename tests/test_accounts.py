"""Unit tests for the multi-account store."""

import base64
import json

import pytest

from arena import accounts


def session_cookie(email, user_id="u1", name="", token="t1"):
    payload = {
        "user": {"id": user_id, "email": email, "user_metadata": {"full_name": name}},
        "access_token": token,
    }
    raw = base64.b64encode(json.dumps(payload).encode()).decode()
    return f"arena-auth-prod-v1.0=base64-{raw}"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(accounts, "COOKIE_FILE", tmp_path / "cookies.txt")
    return accounts, tmp_path


def test_migrates_the_existing_single_cookie(store):
    acc, tmp = store
    cookie = session_cookie("old@example.com", name="Old")
    (tmp / "cookies.txt").write_text(cookie, encoding="utf-8")
    listed = acc.list_accounts()
    assert len(listed) == 1 and listed[0]["email"] == "old@example.com" and listed[0]["active"]
    assert acc.active_cookie() == cookie
    assert (tmp / "cookies.txt").read_text(encoding="utf-8") == cookie


def test_adds_dedupes_switches_and_removes(store):
    acc, tmp = store
    a = session_cookie("a@example.com", "ua", "Alice", "token-a")
    b = session_cookie("b@example.com", "ub", "Bob", "token-b")
    acc.remember(a)
    acc.remember(b)
    assert [x["email"] for x in acc.list_accounts()] == ["a@example.com", "b@example.com"]
    assert acc.active_account()["email"] == "b@example.com"

    newer_a = session_cookie("a@example.com", "ua", "Alice", "token-a2")
    acc.remember(newer_a)
    assert len(acc.list_accounts()) == 2
    assert acc.active_account()["cookie"] == newer_a

    bob = next(x for x in acc.list_accounts() if x["email"] == "b@example.com")
    acc.set_active(bob["id"])
    assert acc.active_account()["email"] == "b@example.com"
    assert (tmp / "cookies.txt").read_text(encoding="utf-8") == b

    alice = next(x for x in acc.list_accounts() if x["email"] == "a@example.com")
    acc.remove(alice["id"])
    assert [x["email"] for x in acc.list_accounts()] == ["b@example.com"]
    acc.remove(bob["id"])
    assert acc.list_accounts() == [] and acc.active_cookie() is None
    assert not (tmp / "cookies.txt").exists()


def test_readding_an_account_keeps_its_id_and_chats(store):
    acc, _ = store
    cookie = session_cookie("a@example.com", "ua")
    first = acc.remember(cookie)
    acc.remove(first["id"])
    again = acc.remember(cookie)
    assert again["id"] == first["id"]


def test_removing_the_active_account_switches_to_the_next(store):
    acc, _ = store
    acc.remember(session_cookie("a@example.com", "ua"))
    acc.remember(session_cookie("b@example.com", "ub"))
    a = next(x for x in acc.list_accounts() if x["email"] == "a@example.com")
    acc.set_active(a["id"])
    kept = acc.remove(a["id"])
    assert kept["email"] == "b@example.com" and kept["active"]
    assert acc.active_account()["email"] == "b@example.com"
