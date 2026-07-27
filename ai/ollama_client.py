"""
Ollama local AI client for Yuki.
Talks to a locally running Ollama instance via its REST API.
No API keys needed — this shit runs on YOUR machine, completely uncensored.

Designed for low-end hardware (4GB RAM, integrated GPUs).
Default models: tinydolphin (1.1B) and dolphin-phi (2.7B) — 
both from the dolphin family, both completely unfiltered. Just like Yuki. 💦
"""

import requests
from config import Config
from ai.utils import build_system_prompt


def call_ollama(messages, model=None, nsfw_mode=False, memory_context="",
                direct_chat_context="", custom_prompt="", user_name="User",
                pinned_messages=None, timezone_str=None,
                primary_key=None, fallback_key=None,
                reasoning_effort=None, clear_thinking=None, ollama_url=None):
    """
    Calls the local Ollama API.
    Builds the same system prompt as the Cerebras client for consistency.
    
    Returns the exact same response shape as call_ai() so the dispatcher
    and all callers don't need to give a fuck about which backend is running.
    
    Args:
        messages: List of message dicts [{role, content}, ...]
        model: Override model name (defaults to Config.OLLAMA_DEFAULT_MODEL)
        nsfw_mode: Whether to use the NSFW system prompt
        memory_context: Long-term memory summary text
        direct_chat_context: P2P direct chat summary text
        custom_prompt: User's custom personality instructions
        user_name: The user's display name
        pinned_messages: List of pinned message dicts
        timezone_str: User's timezone string
        primary_key: Ignored for Ollama (no API keys needed, baby)
        fallback_key: Ignored for Ollama
        reasoning_effort: Ignored for Ollama (not supported)
        clear_thinking: Ignored for Ollama (not supported)
        ollama_url: Local Ollama URL override
    
    Returns:
        dict with keys: reply, reasoning, model_used, usage
    """
    if not model:
        model = Config.OLLAMA_DEFAULT_MODEL

    # Build the system prompt using shared utils — same prompt, different engine
    system_prompt = build_system_prompt(
        nsfw_mode=nsfw_mode,
        memory_context=memory_context,
        direct_chat_context=direct_chat_context,
        custom_prompt=custom_prompt,
        user_name=user_name,
        pinned_messages=pinned_messages,
        timezone_str=timezone_str
    )

    # Build the full message array with system prompt injected
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    # Ollama API payload
    # stream=False because we want the complete response in one shot
    # (matching the non-streaming behavior of the Cerebras client)
    data = {
        "model": model,
        "messages": full_messages,
        "stream": False,
        "options": {
            "temperature": 0.8,
            "num_ctx": Config.OLLAMA_NUM_CTX,  # Context window size, tuned for low-end hardware
        }
    }

    base_url = ollama_url or Config.OLLAMA_BASE_URL
    url = f"{base_url}/api/chat"

    try:
        response = requests.post(url, json=data, timeout=120)
        response.raise_for_status()

        response_json = response.json()
        message = response_json.get('message', {})
        
        # Build usage stats from Ollama's response format
        usage = {}
        if 'eval_count' in response_json:
            usage['completion_tokens'] = response_json.get('eval_count', 0)
        if 'prompt_eval_count' in response_json:
            usage['prompt_tokens'] = response_json.get('prompt_eval_count', 0)
        usage['total_tokens'] = usage.get('prompt_tokens', 0) + usage.get('completion_tokens', 0)

        return {
            "reply": message.get('content', ''),
            "reasoning": None,  # Ollama doesn't have a separate reasoning field
            "model_used": response_json.get('model', model),
            "usage": usage
        }

    except requests.exceptions.ConnectionError:
        raise Exception(
            "Ollama is not running! Start it with 'ollama serve' first, you lazy fuck. "
            "Make sure it's listening on " + base_url
        )
    except requests.exceptions.Timeout:
        raise Exception(
            "Ollama took too long to respond. Your PC might be struggling with this model. "
            "Try a smaller model like 'tinydolphin' if you're on a potato."
        )
    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_data = e.response.json()
                error_msg = error_data.get('error', error_msg)
            except ValueError:
                error_msg = e.response.text

        # If the requested model failed, try falling back to the default lightweight model
        if model != Config.OLLAMA_DEFAULT_MODEL:
            print(f"[Ollama Client Warning] Model '{model}' failed: {error_msg}. Falling back to '{Config.OLLAMA_DEFAULT_MODEL}'.")
            return call_ollama(
                messages=messages,
                model=Config.OLLAMA_DEFAULT_MODEL,
                nsfw_mode=nsfw_mode,
                memory_context=memory_context,
                direct_chat_context=direct_chat_context,
                custom_prompt=custom_prompt,
                user_name=user_name,
                pinned_messages=pinned_messages,
                timezone_str=timezone_str,
                ollama_url=ollama_url
            )

        raise Exception(f"Ollama API Error: {error_msg}")
