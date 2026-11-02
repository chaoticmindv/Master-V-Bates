"""
OpenAI-compatible /v1 API adapter for Arena Desktop.
Translates OpenAI schemas to/from Arena.ai internal formats, handles model routing,
formats SSE streaming chunks, and maintains a thread-safe in-memory request log & stats buffer.
"""

from collections import deque
from datetime import datetime, timezone
import json
import logging
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

LOG = logging.getLogger("arena.openai")


class OpenAILogger:
    """Thread-safe ring buffer for OpenAI API request logs and metrics."""

    def __init__(self, max_records: int = 250):
        self._max = max_records
        self._records = deque(maxlen=max_records)
        self._lock = threading.Lock()
        self._stats = {
            "total_requests": 0,
            "success_count": 0,
            "error_count": 0,
            "challenge_count": 0,
            "total_latency_ms": 0,
        }

    def log_request(
        self,
        req_id: str,
        model: str,
        resolved_model_id: Optional[str],
        status_code: int,
        duration_ms: int,
        stream: bool,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        error: Optional[str] = None,
        challenge: bool = False,
    ):
        record = {
            "id": req_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "time_str": datetime.now().strftime("%H:%M:%S"),
            "model": model,
            "model_id": resolved_model_id or model,
            "status": status_code,
            "duration_ms": max(1, duration_ms),
            "stream": stream,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "error": error,
            "challenge": challenge,
        }
        with self._lock:
            self._records.appendleft(record)
            self._stats["total_requests"] += 1
            if 200 <= status_code < 400:
                self._stats["success_count"] += 1
            else:
                self._stats["error_count"] += 1
            if challenge:
                self._stats["challenge_count"] += 1
            self._stats["total_latency_ms"] += max(1, duration_ms)

    def get_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._records)[:limit]

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._stats["total_requests"]
            avg_lat = round(self._stats["total_latency_ms"] / total) if total > 0 else 0
            success_rate = round((self._stats["success_count"] / total) * 100, 1) if total > 0 else 100.0
            return {
                "total_requests": total,
                "success_count": self._stats["success_count"],
                "error_count": self._stats["error_count"],
                "challenge_count": self._stats["challenge_count"],
                "avg_latency_ms": avg_lat,
                "success_rate": success_rate,
                "recent_count": len(self._records),
            }

    def clear(self):
        with self._lock:
            self._records.clear()
            self._stats = {
                "total_requests": 0,
                "success_count": 0,
                "error_count": 0,
                "challenge_count": 0,
                "total_latency_ms": 0,
            }


API_LOGGER = OpenAILogger()


def _normalize_name(name: str) -> str:
    """Normalize string for fuzzy matching (lowercase, alphanumeric only)."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def resolve_model(model_param: str, all_models: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    """
    Given a model name from the OpenAI request (e.g. 'claude-3-7-sonnet', 'gpt-4o', or a UUID),
    resolve to (arena_model_id, display_name).
    """
    if not model_param:
        return None, None

    model_clean = model_param.strip().lower()
    norm_param = _normalize_name(model_param)

    # 1. Exact ID match
    for m in all_models:
        if m.get("id") == model_param:
            return m["id"], m.get("name") or m.get("public_name")

    # 2. Exact public_name or display name match (case-insensitive)
    for m in all_models:
        p_name = (m.get("public_name") or "").lower()
        d_name = (m.get("name") or "").lower()
        if model_clean == p_name or model_clean == d_name:
            return m["id"], m.get("name") or m.get("public_name")

    # 3. Normalized alphanumeric match
    for m in all_models:
        if norm_param == _normalize_name(m.get("public_name") or "") or norm_param == _normalize_name(m.get("name") or ""):
            return m["id"], m.get("name") or m.get("public_name")

    # 4. Prefix / Substring match (e.g. 'claude-3-7-sonnet' matching 'claude-3-7-sonnet-20250219')
    for m in all_models:
        p_norm = _normalize_name(m.get("public_name") or "")
        d_norm = _normalize_name(m.get("name") or "")
        if norm_param in p_norm or norm_param in d_norm or p_norm.startswith(norm_param):
            return m["id"], m.get("name") or m.get("public_name")

    # Fallback: if it matches a UUID format, allow it as a direct arena model ID; otherwise None
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", model_param):
        return model_param, model_param
    return None, None


def format_model_list(all_models: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Format Arena model catalog into OpenAI GET /v1/models response."""
    data = []
    seen_ids = set()

    # Prioritize user selectable and chat/code models
    for m in all_models:
        m_id = m.get("id")
        if not m_id or m_id in seen_ids:
            continue
        seen_ids.add(m_id)

        org = m.get("org") or "arena.ai"
        display_name = m.get("name") or m.get("public_name") or m_id
        public_name = m.get("public_name") or display_name

        item = {
            "id": m_id,
            "object": "model",
            "created": 1700000000,
            "owned_by": org,
            "permission": [],
            "root": m_id,
            "parent": None,
            "display_name": display_name,
            "public_name": public_name,
            "modality": m.get("arena", "text"),
        }
        data.append(item)

        # Also register the public_name as a top-level model ID if it doesn't collide,
        # so clients can call e.g. "model": "claude-3-7-sonnet" directly.
        if public_name and public_name not in seen_ids:
            seen_ids.add(public_name)
            alias_item = dict(item)
            alias_item["id"] = public_name
            alias_item["root"] = m_id
            data.append(alias_item)

    return {"object": "list", "data": data}


def format_messages_to_prompt(messages: List[Dict[str, Any]]) -> str:
    """
    Format standard OpenAI messages array into prompt string for Arena.ai.
    If multiple turns or system prompts exist, formats them cleanly.
    """
    if not messages:
        return ""

    if len(messages) == 1 and messages[0].get("role") == "user":
        content = messages[0].get("content")
        if isinstance(content, list):
            # Extract text parts from multimodal array
            texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            return "\n".join(texts)
        return str(content or "")

    parts = []
    system_prompts = []

    for msg in messages:
        role = (msg.get("role") or "user").strip().lower()
        raw_content = msg.get("content") or ""
        if isinstance(raw_content, list):
            text = "\n".join(c.get("text", "") for c in raw_content if isinstance(c, dict) and c.get("type") == "text")
        else:
            text = str(raw_content)

        if role == "system":
            system_prompts.append(text)
        elif role == "user":
            parts.append(f"User: {text}")
        elif role == "assistant":
            parts.append(f"Assistant: {text}")
        else:
            parts.append(f"{role.capitalize()}: {text}")

    full_prompt = ""
    if system_prompts:
        full_prompt += "System Instructions:\n" + "\n\n".join(system_prompts) + "\n\n"

    # If the last message is from user and there are prior turns, format full history
    full_prompt += "\n\n".join(parts)
    return full_prompt.strip()


def estimate_tokens(text: str) -> int:
    """Fast approximation of token count (~4 characters per token)."""
    return max(1, len(text or "") // 4)


def format_openai_sse_chunk(
    req_id: str,
    model: str,
    content: Optional[str] = None,
    reasoning: Optional[str] = None,
    finish_reason: Optional[str] = None,
) -> str:
    """Generate an OpenAI SSE chunk (data: {...}\n\n)."""
    delta: Dict[str, Any] = {}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning_content"] = reasoning

    choice: Dict[str, Any] = {
        "index": 0,
        "delta": delta,
        "finish_reason": finish_reason,
    }

    chunk = {
        "id": req_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [choice],
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


def format_openai_completion(
    req_id: str,
    model: str,
    content: str,
    reasoning: Optional[str] = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> Dict[str, Any]:
    """Generate standard OpenAI non-streaming chat.completion JSON object."""
    message: Dict[str, Any] = {
        "role": "assistant",
        "content": content,
    }
    if reasoning:
        message["reasoning_content"] = reasoning

    return {
        "id": req_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def format_openai_error(message: str, error_type: str = "invalid_request_error", code: int = 400) -> Dict[str, Any]:
    """Generate standard OpenAI error envelope."""
    return {
        "error": {
            "message": message,
            "type": error_type,
            "param": None,
            "code": code,
        }
    }
