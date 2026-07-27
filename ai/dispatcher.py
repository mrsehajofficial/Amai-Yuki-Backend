"""
AI Provider Dispatcher for Yuki.
The single entry point for ALL AI calls across the entire backend.

Routes to the correct provider (Cerebras cloud or Ollama local) based on:
1. Per-request 'provider' param (highest priority)
2. User's saved DB preference
3. Config.DEFAULT_PROVIDER (fallback)

Both backends return the exact same response dict shape, so callers
don't need to know or care which engine is actually doing the work.
Yuki speaks through whatever throat is available. 😏
"""

from config import Config


def dispatch_ai(messages, provider=None, primary_key=None, fallback_key=None,
                model=None, nsfw_mode=False, memory_context="",
                direct_chat_context="", custom_prompt="", user_name="User",
                pinned_messages=None, timezone_str=None,
                reasoning_effort=None, clear_thinking=None, ollama_url=None):
    """
    Universal AI dispatcher. Routes to the correct backend based on provider.
    
    Args:
        messages: List of message dicts [{role, content}, ...]
        provider: 'cerebras' or 'ollama' (None = use Config.DEFAULT_PROVIDER)
        primary_key: API key for Cerebras (ignored by Ollama)
        fallback_key: Fallback API key for Cerebras (ignored by Ollama)
        model: Model name override
        nsfw_mode: Whether to use NSFW system prompt
        memory_context: Long-term memory summary
        direct_chat_context: P2P chat context summary
        custom_prompt: User custom personality instructions
        user_name: User's display name
        pinned_messages: Pinned messages list
        timezone_str: User's timezone
        reasoning_effort: Cerebras-specific param
        clear_thinking: Cerebras-specific param
        ollama_url: Local Ollama URL override
    
    Returns:
        dict: {reply, reasoning, model_used, usage}
    """
    # Resolve which provider to use
    if not provider:
        provider = Config.DEFAULT_PROVIDER
    
    provider = provider.strip().lower()
 
    if provider == 'ollama':
        from ai.ollama_client import call_ollama
        
        # Resolve model for Ollama — if the model is a Cerebras model name,
        # we need to map it to an Ollama model or use the default
        resolved_model = Config.resolve_ollama_model(model) if model else None
        
        return call_ollama(
            messages=messages,
            model=resolved_model,
            nsfw_mode=nsfw_mode,
            memory_context=memory_context,
            direct_chat_context=direct_chat_context,
            custom_prompt=custom_prompt,
            user_name=user_name,
            pinned_messages=pinned_messages,
            timezone_str=timezone_str,
            primary_key=primary_key,
            fallback_key=fallback_key,
            reasoning_effort=reasoning_effort,
            clear_thinking=clear_thinking,
            ollama_url=ollama_url
        )
    else:
        # Default: Cerebras cloud API
        from ai.client import call_ai
        
        return call_ai(
            messages=messages,
            primary_key=primary_key,
            fallback_key=fallback_key,
            model= Config.DEFAULT_MODEL,
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
