import requests
import os
from config import Config
from datetime import datetime, timedelta, timezone

def get_local_time_str(tz_name_or_offset):
    """
    Robustly computes current local time as a string based on timezone name or offset.
    Handles 'Asia/Kolkata', 'UTC+5:30', '+05:30', 'GMT-4:00', etc.
    """
    try:
        from zoneinfo import ZoneInfo
        clean_tz = tz_name_or_offset.replace("UTC", "").replace("GMT", "").strip()
        if clean_tz.startswith("+") or clean_tz.startswith("-"):
            sign = 1 if clean_tz[0] == '+' else -1
            parts = clean_tz[1:].split(':')
            hours = int(parts[0])
            minutes = int(parts[1]) if len(parts) > 1 else 0
            tz = timezone(timedelta(hours=sign * hours, minutes=sign * minutes))
        else:
            tz = ZoneInfo(tz_name_or_offset)
        
        now = datetime.now(tz)
        return now.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        # Fallback parsing
        try:
            clean_tz = tz_name_or_offset.replace("UTC", "").replace("GMT", "").strip()
            if clean_tz.startswith("+") or clean_tz.startswith("-"):
                sign = 1 if clean_tz[0] == '+' else -1
                parts = clean_tz[1:].split(':')
                hours = int(parts[0])
                minutes = int(parts[1]) if len(parts) > 1 else 0
                tz = timezone(timedelta(hours=sign * hours, minutes=sign * minutes))
                now = datetime.now(tz)
                return now.strftime("%Y-%m-%d %H:%M:%S") + f" (UTC{clean_tz})"
        except Exception:
            pass
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

def load_prompt(nsfw_mode=False):
    filename = 'nsfw.md' if nsfw_mode else 'sfw.md'
    prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts', filename)
    
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()

def call_ai(messages, primary_key, fallback_key=None, model=Config.DEFAULT_MODEL, nsfw_mode=False, memory_context="", direct_chat_context="", custom_prompt="", user_name="User", pinned_messages=None, timezone_str=None, reasoning_effort=None, clear_thinking=None):
    """
    Calls the LongCat AI API.
    Injects system prompt, memory context, custom user personality, pinned messages, and user's timezone.
    Falls back to fallback_key if primary_key fails with 401 or 429.
    """
    # 1. Prepare system prompt
    raw_prompt = load_prompt(nsfw_mode)
    base_prompt = raw_prompt.replace("{memory}", memory_context if memory_context else "No prior history recorded yet.")
    base_prompt = base_prompt.replace("{user_name}", user_name)
    
    # Inject Direct Chat Summary (P2P interactions) if present. This allows Yuki to have
    # full contextual awareness of who the user has been talking to and what they've discussed.
    if direct_chat_context:
        base_prompt += f"\n\n[USER DIRECT MESSAGES & SOCIAL CONTEXT]\nThe user has been chatting with other people on the platform. Here is a summary of their recent conversations, plans, agreements, and relationships with other users. You can use this context to reference their friends or peer-to-peer activities naturally if appropriate:\n{direct_chat_context}\n"
    
    # Inject Pinned Messages
    if pinned_messages:
        pinned_text = "\n".join([f"{'User' if p['role'] == 'user' else 'Yuki'}: {p['content']}" for p in pinned_messages])
        base_prompt += f"\n\n[PINNED CORE MEMORY]\nThe following messages were pinned by the user as extremely important to remember:\n{pinned_text}\n"

    # Inject Timezone & Local Time
    # Hey! We want Yuki to know the time context (is it late? morning?) but we absolutely
    # do NOT want her parroting this time or forcing a "good morning" on every single turn.
    # So we provide this as passive system context and tell her to keep it completely natural.
    if timezone_str:
        local_time = get_local_time_str(timezone_str)
        base_prompt += (
            f"\n\n[USER SYSTEM TIME & TIMEZONE]\n"
            f"The user's current timezone is: {timezone_str}\n"
            f"The user's exact current local date and time is: {local_time}\n"
            f"USAGE INSTRUCTION: Use this system time purely as passive background context to understand the user's daily cycle. "
            f"Do NOT mention this time, do NOT say 'I see it is [time]', and do NOT force greetings (like morning/night) "
            f"on every message unless the user asks for the time or the current time genuinely and naturally context-warrants it.\n"
        )

    # 2. Add custom personality if provided
    if custom_prompt:
        base_prompt += f"\n\n[USER CUSTOM PERSONALITY INSTRUCTIONS]\n{custom_prompt}\n"

    # 3. Build full message array
    full_messages = [{"role": "system", "content": base_prompt}] + messages
    
    data = {
        "model": model,
        "messages": full_messages,
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
