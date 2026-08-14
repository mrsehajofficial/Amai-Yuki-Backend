import requests
from config import Config
from ai.utils import build_system_prompt


def call_ai(messages, primary_key, fallback_key=None, model=Config.DEFAULT_MODEL, nsfw_mode=False, memory_context="", direct_chat_context="", custom_prompt="", user_name="User", pinned_messages=None, timezone_str=None, reasoning_effort=None, clear_thinking=None):
    """
    Calls the Cerebras cloud AI API.
    Injects system prompt, memory context, custom user personality, pinned messages, and user's timezone.
    Falls back to fallback_key if primary_key fails with 401 or 429.
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

    # Helper function to make the request
    def _make_request(api_key):
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        response = requests.post(Config.AI_BASE_URL, headers=headers, json=data, timeout=30)
        return response

    # Try primary key
    try:
        res = _make_request(primary_key)
        
        # If it's a rate limit or auth error, and we have a fallback key, try the fallback
        if res.status_code in [401, 429] and fallback_key:
            res = _make_request(fallback_key)
            
        res.raise_for_status()
        
        response_json = res.json()
        message = response_json['choices'][0]['message']
        return {
            "reply": message['content'],
            "reasoning": message.get('reasoning'),
            "model_used": response_json.get('model', model),
            "usage": response_json.get('usage', {})
        }
        
    except requests.exceptions.RequestException as e:
        # Extract API error message if available
        error_msg = str(e)
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_data = e.response.json()
                error_msg = error_data.get('error', {}).get('message', error_msg)
            except ValueError:
                error_msg = e.response.text
        
        # Hey! If the premium/preview model failed (e.g. rate limit, exhausted quota),
        # we don't want to throw a nasty 500 error and leave the user stranded.
        # Instead, we gracefully fall back to our ultra-reliable default chat model.
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
