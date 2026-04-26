import os
from typing import Annotated, Any, Generator
import requests as _requests
from fastapi import Depends, HTTPException, status
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from utils import register_util
from utils.oauth2 import oauth2_scheme
from utils.registry import get_util_registry

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
# These models only accept `thinking={"type":"adaptive"}`.
ADAPTIVE_THINKING_ONLY_MODELS: frozenset[str] = frozenset({
    "claude-opus-4-7",
})
VISIBLE_THINKING_DISPLAY = "summarized"

_CHATBOT_ENABLED = os.environ.get("VITE_ENABLE_CHATBOT", "True").lower() == "true"


class ChatbotMessagesInput(BaseModel):
    messages: list[dict]
    tools: list[dict] | None = None
    max_tokens: int = 16000
    stream: bool = True
    thinking: dict | None = None


def _normalize_thinking_for_model(payload: dict, model: str) -> None:
    """Normalize `thinking` for the target Claude model."""
    thinking = payload.get("thinking")
    if not isinstance(thinking, dict):
        return

    if model in ADAPTIVE_THINKING_ONLY_MODELS and thinking.get("type") == "enabled":
        payload["thinking"] = {
            "type": "adaptive",
            "display": VISIBLE_THINKING_DISPLAY,
        }
        return

    if thinking.get("type") in {"enabled", "adaptive"}:
        thinking.setdefault("display", VISIBLE_THINKING_DISPLAY)


class ChatbotProxyController:

    prefixes = ["chatbot"]
    methods_to_bind: dict[str, list[str]] = {
        "messages": ["POST"],
    }

    def __init__(self, util_config: dict[str, Any]):
        pass

    def _get_credentials(self) -> tuple[str, str, str | None]:
        """Return (api_key, model, system_prompt) from chatbot_config_controller."""
        config = get_util_registry().get_util("chatbot_config_controller")
        if config is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Chatbot config controller not available",
            )
        api_key = config.get("CLAUDE_API_KEY")
        model = config.get("CLAUDE_MODEL")
        if not api_key or not model:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Claude credentials (CLAUDE_API_KEY / CLAUDE_MODEL) not configured",
            )
        system_prompt = config.get("CHATBOT_SYSTEM_PROMPT")
        return api_key, model, system_prompt

    def messages(
        self,
        body: ChatbotMessagesInput,
        token: Annotated[str, Depends(oauth2_scheme)],
    ) -> Response:
        api_key, model, system_prompt = self._get_credentials()

        payload = body.model_dump(exclude_none=True)
        payload["model"] = model
        _normalize_thinking_for_model(payload, model)
        if system_prompt:
            payload["system"] = system_prompt

        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
            "accept-encoding": "identity",
        }

        if body.stream:
            headers["accept"] = "text/event-stream"
            upstream = _requests.post(
                ANTHROPIC_MESSAGES_URL,
                headers=headers,
                json=payload,
                stream=True,
                timeout=120,
            )

            if upstream.status_code >= 400:
                extra_headers = {}
                retry_after = upstream.headers.get("retry-after")
                if retry_after:
                    extra_headers["retry-after"] = retry_after
                upstream.close()
                raise HTTPException(
                    status_code=upstream.status_code,
                    detail=f"Upstream Claude API error {upstream.status_code}",
                    headers=extra_headers or None,
                )

            def sse_generator() -> Generator[bytes, None, None]:
                with upstream:
                    for chunk in upstream.iter_content(chunk_size=None):
                        if chunk:
                            yield chunk

            return StreamingResponse(sse_generator(), media_type="text/event-stream")

        resp = _requests.post(
            ANTHROPIC_MESSAGES_URL,
            headers=headers,
            json=payload,
            timeout=120,
        )
        return JSONResponse(content=resp.json(), status_code=resp.status_code)


if _CHATBOT_ENABLED:
    ChatbotProxyController = register_util(
        name="chatbot_proxy_controller"
    )(ChatbotProxyController)
