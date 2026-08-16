import requests
from config import Config
from ai.utils import build_system_prompt

# Error markers that mean "your key is bad or you're being throttled" —
# the same situations where the old direct client used HTTP 401/429.
_TRANSIENT_TAXONOMY = (
    'api key', 'unauthorized', 'authentication', 'invalid', '401',
    'rate limit', 'too many requests', '429', 'quota', 'try again later',
)


def _extract_error(response):
    """
    Parses a proxy response and returns (error_message, transient, body).

    The Apps Script proxy always answers HTTP 200 (ContentService cannot send
    custom status codes), so failures are detected from the JSON body:
      - success:     {"choices": [...], "model": ..., "usage": {...}}
      - ByNara err:  {"error": {"message": "...", "type": "..."}}
      - proxy err:   {"error": "Missing API key"} etc.

    Returns:
        error_message: None on success, else a human-readable message
        transient: True when the failure is auth/rate-limit-ish (worth trying
                   the fallback key)
        body: the parsed OpenAI-style JSON dict on success, else None
    """
    try:
        body = response.json()
    except ValueError:
        return (f"AI proxy returned a non-JSON response "
                f"(HTTP {response.status_code}): {response.text[:300]}"), False, None

    if not isinstance(body, dict):
        return f"AI proxy returned an unexpected payload (HTTP {response.status_code})", False, None

    if body.get('choices'):
        return None, False, body

    err = body.get('error')
    if err is not None:
        if isinstance(err, dict):
            message = err.get('message') or str(err)
            err_type = str(err.get('type', '')).lower()
            code = str(err.get('code', '') or err.get('status', '')).lower()
        else:
            message = str(err)
            err_type, code = '', ''
        haystack = f"{err_type} {code} {message}".lower()
        return message, any(marker in haystack for marker in _TRANSIENT_TAXONOMY), None

    return "AI proxy returned an unexpected payload", False, None


def _format_request_exception(error):
    """Turns a requests.RequestException into a readable error message."""
    error_msg = str(error)
    if hasattr(error, 'response') and error.response is not None:
        try:
            error_data = error.response.json()
            error_msg = error_data.get('error', {}).get('message', error_msg)
        except ValueError:
            error_msg = error.response.text
    return error_msg


def call_ai(messages, primary_key, fallback_key=None, model=Config.DEFAULT_MODEL, nsfw_mode=False, memory_context="", direct_chat_context="", custom_prompt="", user_name="User", pinned_messages=None, timezone_str=None, reasoning_effort=None, clear_thinking=None):
    """
    Calls the ByNara cloud AI via the Google Apps Script proxy.

    Architecture:
        PythonAnywhere (this backend) → Apps Script proxy (no keys stored) → ByNara

    The ByNara key comes ONLY from the user's own creds.db record (primary_key /
    fallback_key) and is forwarded to the proxy once per request — it lives only
    on this server and is never stored or persisted by Apps Script.
    Falls back to fallback_key if primary_key fails with auth/rate-limit errors.
    """
    # 1. Build system prompt using shared utility
    base_prompt = build_system_prompt(
        nsfw_mode=nsfw_mode,
        memory_context=memory_context,
        direct_chat_context=direct_chat_context,
        custom_prompt=custom_prompt,
        user_name=user_name,
        pinned_messages=pinned_messages,
        timezone_str=timezone_str
    )

    # 2. Build full message array
    full_messages = [{"role": "system", "content": base_prompt}] + messages
    
    data = {
        "model": model,
        "messages": full_messages,
        "stream": False,
        "max_tokens": 2000,
        "temperature": 0.8
    }
    if reasoning_effort is not None:
        data["reasoning_effort"] = reasoning_effort
    if clear_thinking is not None:
        data["clear_thinking"] = clear_thinking

    # The ByNara key comes straight from the user's creds.db record (primary_key
    # / fallback_key) and is passed through bare — no shared server key involved.

    # Send the request through the static Apps Script proxy. The key rides
    # along as a query param (that's what the deployed proxy expects), gets
    # turned into the Authorization header by the proxy, and dies with the
    # request — Apps Script never persists it.
    def _make_request(api_key):
        return requests.post(
            Config.AI_PROXY_URL,
            params={"api_key": api_key},
            headers={"Content-Type": "application/json"},
            json=data,
            timeout=Config.AI_REQUEST_TIMEOUT
        )

    def _attempt(api_key):
        """One end-to-end attempt: proxy call + error classification."""
        try:
            return _extract_error(_make_request(api_key))
        except requests.exceptions.RequestException as e:
            return _format_request_exception(e), True, None

    # Try the primary key first.
    error_msg, transient, response_json = _attempt(primary_key)

    # On auth/rate-limit failures with a fallback key available, try it.
    if error_msg and transient and fallback_key:
        error_msg, transient, response_json = _attempt(fallback_key)

    if error_msg is not None:
        # Hey! If the premium/preview model failed (e.g. rate limit, exhausted
        # quota), we don't want to throw a nasty 500 error and leave the user
        # stranded. Instead, we gracefully fall back to our ultra-reliable
        # default chat model.
        if model != Config.DEFAULT_MODEL:
            print(f"[AI Client Warning] Model '{model}' failed with error: {error_msg}. Gracefully falling back to default '{Config.DEFAULT_MODEL}'.")
            return call_ai(
                messages=messages,
                primary_key=primary_key,
                fallback_key=fallback_key,
                model=Config.DEFAULT_MODEL,
                nsfw_mode=nsfw_mode,
                memory_context=memory_context,
                direct_chat_context=direct_chat_context,
                custom_prompt=custom_prompt,
                user_name=user_name,
                pinned_messages=pinned_messages,
                timezone_str=timezone_str,
                reasoning_effort=reasoning_effort,
                clear_thinking=clear_thinking
            )

        raise Exception(f"AI API Error: {error_msg}")

    message = response_json['choices'][0]['message']
    return {
        "reply": message['content'],
        "reasoning": message.get('reasoning'),
        "model_used": response_json.get('model', model),
        "usage": response_json.get('usage', {})
    }
