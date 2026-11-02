import json
import pytest
from unittest.mock import patch, MagicMock
from arena.web.app import app
from arena.web.openai_compat import (
    API_LOGGER,
    resolve_model,
    format_model_list,
    format_messages_to_prompt,
    format_openai_sse_chunk,
    format_openai_completion,
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def clean_logger():
    API_LOGGER.clear()
    yield
    API_LOGGER.clear()


def test_openai_model_list(client):
    res = client.get("/v1/models")
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("object") == "list"
    assert isinstance(data.get("data"), list)
    assert len(data["data"]) > 0
    first = data["data"][0]
    assert "id" in first
    assert first["object"] == "model"
    assert "owned_by" in first


def test_model_resolution():
    mock_models = [
        {"id": "claude-uuid-1", "name": "Claude 3.7 Sonnet", "public_name": "claude-3-7-sonnet-20250219", "org": "anthropic"},
        {"id": "gpt-uuid-2", "name": "GPT-4o", "public_name": "gpt-4o", "org": "openai"},
        {"id": "deepseek-uuid-3", "name": "DeepSeek R1", "public_name": "deepseek-r1", "org": "deepseek"},
    ]
    # Exact ID
    assert resolve_model("claude-uuid-1", mock_models)[0] == "claude-uuid-1"
    # Exact public name
    assert resolve_model("gpt-4o", mock_models)[0] == "gpt-uuid-2"
    # Fuzzy/normalized alias
    assert resolve_model("claude-3-7-sonnet", mock_models)[0] == "claude-uuid-1"
    assert resolve_model("deepseek-r1", mock_models)[0] == "deepseek-uuid-3"


def test_prompt_formatting():
    # Single message
    msgs = [{"role": "user", "content": "Hello world"}]
    assert format_messages_to_prompt(msgs) == "Hello world"

    # Multi-turn
    msgs = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "What is 2+2?"},
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "Multiply by 2"},
    ]
    formatted = format_messages_to_prompt(msgs)
    assert "System Instructions:\nYou are helpful." in formatted
    assert "User: What is 2+2?" in formatted
    assert "Assistant: 4" in formatted
    assert "User: Multiply by 2" in formatted


def test_chat_completions_validation(client):
    # Empty body
    res = client.post("/v1/chat/completions", json={})
    assert res.status_code == 400
    assert "error" in res.get_json()

    # Empty messages list
    res = client.post("/v1/chat/completions", json={"messages": []})
    assert res.status_code == 400
    assert "error" in res.get_json()

    # Invalid / empty model
    res = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}], "model": ""})
    assert res.status_code in (400, 404)


class MockStreamResponse:
    def __init__(self, chunks, status_code=200):
        self.status_code = status_code
        self._chunks = chunks
        self.text = "".join(chunks)

    def iter_text(self):
        for c in self._chunks:
            yield c


@patch("arena.web.app.sync_models", return_value=[{"id": "gpt-uuid-test", "public_name": "gpt-4o", "name": "GPT-4o"}])
@patch("arena.web.app._signed_in_somewhere", return_value=True)
@patch("arena.web.app._v1_execute_turn")
def test_chat_completions_non_streaming(mock_turn, mock_auth, mock_models, client):
    # Mock Arena SSE response with text and reasoning
    mock_r = MockStreamResponse([
        'ag:"I am thinking..."\n',
        'a0:"Hello"\n',
        'a0:" there!"\n',
        'ad:{"finishReason":"stop"}\n'
    ])
    mock_turn.return_value = (mock_r, None, 200, False)

    res = client.post("/v1/chat/completions", json={
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Say hello"}],
        "stream": False
    })

    assert res.status_code == 200
    data = res.get_json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"] == "Hello there!"
    assert data["choices"][0]["message"]["reasoning_content"] == "I am thinking..."
    assert data["usage"]["total_tokens"] > 0

    # Verify log entry in API_LOGGER
    stats = API_LOGGER.get_stats()
    assert stats["total_requests"] == 1
    assert stats["success_count"] == 1


@patch("arena.web.app.sync_models", return_value=[{"id": "gpt-uuid-test", "public_name": "gpt-4o", "name": "GPT-4o"}])
@patch("arena.web.app._signed_in_somewhere", return_value=True)
@patch("arena.web.app._v1_execute_turn")
def test_chat_completions_streaming(mock_turn, mock_auth, mock_models, client):
    mock_r = MockStreamResponse([
        'ag:"Reasoning step"\n',
        'a0:"Streaming response"\n',
    ])
    mock_turn.return_value = (mock_r, None, 200, False)

    res = client.post("/v1/chat/completions", json={
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Stream to me"}],
        "stream": True
    })

    assert res.status_code == 200
    assert "text/event-stream" in res.headers.get("Content-Type", "")
    data = res.get_data(as_text=True)
    assert "data: " in data
    assert "[DONE]" in data
    assert "Streaming response" in data


def test_api_stats_and_logs(client):
    # Add a mock request log
    API_LOGGER.log_request("req-1", "gpt-4o", "mock-id", 200, 150, False, 10, 20, None, False)
    res = client.get("/api/v1/stats")
    assert res.status_code == 200
    data = res.get_json()
    assert "stats" in data
    assert data["stats"]["total_requests"] == 1
    assert len(data["logs"]) == 1
    assert data["logs"][0]["id"] == "req-1"
    assert "base_url" in data

    # Clear logs
    res_clear = client.post("/api/v1/logs/clear")
    assert res_clear.status_code == 200
    data_after = client.get("/api/v1/stats").get_json()
    assert data_after["stats"]["total_requests"] == 0
    assert len(data_after["logs"]) == 0


@patch("arena.web.app.sync_models", return_value=[{"id": "gpt-uuid-test", "public_name": "gpt-4o", "name": "GPT-4o"}])
@patch("arena.web.app._signed_in_somewhere", return_value=True)
@patch("arena.web.app._v1_execute_turn")
def test_cors_headers(mock_turn, mock_auth, mock_models, client):
    mock_r = MockStreamResponse(['a0:"CORS test"\n'])
    mock_turn.return_value = (mock_r, None, 200, False)

    res = client.post("/v1/chat/completions",
                      headers={"Origin": "http://localhost:3000"},
                      json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]})
    assert res.status_code == 200
    assert res.headers.get("Access-Control-Allow-Origin") == "*"
