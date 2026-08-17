import requests
from config import Config
from ai.utils import build_system_prompt

# Error markers that mean "your key is bad or you're being throttled"
_TRANSIENT_TAXONOMY = (
    'api key', 'unauthorized', 'authentication', 'invalid', '401',
    'rate limit', 'too many requests', '429', 'quota', 'try again later',
)


def _extract_error(response):
    """
    Parses an API response and returns (error_message, transient, body).
    
    Handles both direct ByNara responses (may return non-200 status codes)
    and proxy responses (always HTTP 200, errors in JSON body).
    
    Returns:
        error_message: None on success, else a human-readable message
        transient: True when the failure is auth/rate-limit-ish (worth trying fallback key)
        body: the parsed OpenAI-style JSON dict on success, else None
    """
    try:
        body = response.json()
    except ValueError:
        return (f"AI returned a non-JSON response "
                f"(HTTP {response.status_code}): {response.text[:300]}"), False, None

    if not isinstance(body, dict):
        return f"AI returned an unexpected payload (HTTP {response.status_code})", False, None

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

    return "AI returned an unexpected payload", False, None


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


def call_ai(messages, primary_key, fallback_key=None, model=Config.DEFAULT_MODEL, nsfw_mode=False, memory_context="", direct_chat_context="", custom_prompt="", user_name="User", pinned_messages=None, timezone_str=None, reasoning_effort=None, clear_thinking=None, latest_message=""):
    """
    Calls the ByNara cloud AI via direct API (fast) with Apps Script proxy fallback.
    
    Flow:
        Primary:  PythonAnywhere → ByNara Router (direct, <1s)
        Fallback: PythonAnywhere → Apps Script Proxy → ByNara Router (slow, ~3-5s)
    
    The ByNara key comes ONLY from the user's own creds.db record (primary_key /
    fallback_key) and is forwarded once per request. Never stored, never persisted.
    Falls back to fallback_key if primary_key fails with auth/rate-limit errors.
    Falls back to proxy if direct call fails with connection/timeout errors.
    """
    # 1. Build system prompt using shared utility
    base_prompt = build_system_prompt(
        nsfw_mode=nsfw_mode,
        memory_context=memory_context,
        direct_chat_context=direct_chat_context,
        custom_prompt=custom_prompt,
        user_name=user_name,
        pinned_messages=pinned_messages,
        timezone_str=timezone_str,
        latest_message=latest_message
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

    # === Direct call to ByNara (fast path) ===
    def _make_direct(api_key):
        return requests.post(
            Config.AI_BASE_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            },
            json=data,
            timeout=Config.AI_REQUEST_TIMEOUT
        )

    # === Proxy call (fallback path) ===
    def _make_proxy(api_key):
        return requests.post(
            Config.AI_PROXY_URL,
            params={"api_key": api_key},
            headers={"Content-Type": "application/json"},
            json=data,
            timeout=Config.AI_REQUEST_TIMEOUT
        )

    def _attempt(api_key, make_fn):
        """One end-to-end attempt: API call + error classification."""
        try:
            return _extract_error(make_fn(api_key))
        except requests.exceptions.RequestException as e:
            return _format_request_exception(e), True, None

    # Try: primary direct → fallback direct → primary proxy → fallback proxy
    error_msg, transient, response_json = _attempt(primary_key, _make_direct)

    # On transient failure (auth/rate-limit), try fallback key on same path
    if error_msg and transient and fallback_key:
        error_msg, transient, response_json = _attempt(fallback_key, _make_direct)

    # On connection/timeout failures, fall back to proxy path
    if error_msg and not response_json:
        error_msg_proxy, transient_proxy, response_json_proxy = _attempt(primary_key, _make_proxy)
        if response_json_proxy is not None:
            error_msg, transient, response_json = error_msg_proxy, transient_proxy, response_json_proxy

        if error_msg and transient and fallback_key:
            _, _, response_json_fb = _attempt(fallback_key, _make_proxy)
            if response_json_fb is not None:
                response_json = response_json_fb

    if error_msg is not None:
        if model != Config.DEFAULT_MODEL:
            print(f"[AI Client Warning] Model '{model}' failed: {error_msg}. Falling back to '{Config.DEFAULT_MODEL}'.")
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
                clear_thinking=clear_thinking,
                latest_message=latest_message
            )

        raise Exception(f"AI API Error: {error_msg}")

    message = response_json['choices'][0]['message']
    return {
        "reply": message['content'],
        "reasoning": message.get('reasoning'),
        "model_used": response_json.get('model', model),
        "usage": response_json.get('usage', {})
    }
