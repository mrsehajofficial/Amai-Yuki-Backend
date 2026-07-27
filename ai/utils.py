"""
Shared AI utilities for Yuki's brain.
Both the Cerebras cloud client and the Ollama local client use these
to build identical system prompts. Keeps Yuki's personality consistent
no matter which cock— I mean, which backend is doing the thinking.
"""

import os
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
    """Loads Yuki's system prompt from the prompts directory."""
    filename = 'nsfw.md' if nsfw_mode else 'sfw.md'
    prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts', filename)
    
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()


def build_system_prompt(nsfw_mode=False, memory_context="", direct_chat_context="",
                        custom_prompt="", user_name="User", pinned_messages=None,
                        timezone_str=None):
    """
    Builds the full system prompt for Yuki — identical output regardless of
    whether we're sending it to Cerebras cloud or Ollama local.
    
    This is the single source of truth for Yuki's personality injection.
    Touch this function and you touch Yuki's soul. Handle with care... or don't. 😈
    """
    # 1. Load base personality prompt
    raw_prompt = load_prompt(nsfw_mode)
    base_prompt = raw_prompt.replace("{memory}", memory_context if memory_context else "No prior history recorded yet.")
    base_prompt = base_prompt.replace("{user_name}", user_name)
    
    # 2. Inject Direct Chat Summary (P2P interactions) if present
    if direct_chat_context:
        base_prompt += (
            f"\n\n[USER DIRECT MESSAGES & SOCIAL CONTEXT]\n"
            f"The user has been chatting with other people on the platform. "
            f"Here is a summary of their recent conversations, plans, agreements, "
            f"and relationships with other users. You can use this context to reference "
            f"their friends or peer-to-peer activities naturally if appropriate:\n"
            f"{direct_chat_context}\n"
        )
    
    # 3. Inject Pinned Messages
    if pinned_messages:
        pinned_text = "\n".join(
            [f"{'User' if p['role'] == 'user' else 'Yuki'}: {p['content']}" for p in pinned_messages]
        )
        base_prompt += (
            f"\n\n[PINNED CORE MEMORY]\n"
            f"The following messages were pinned by the user as extremely important to remember:\n"
            f"{pinned_text}\n"
        )

    # 4. Inject Timezone & Local Time
    if timezone_str:
        local_time = get_local_time_str(timezone_str)
        base_prompt += (
            f"\n\n[USER SYSTEM TIME & TIMEZONE]\n"
            f"The user's current timezone is: {timezone_str}\n"
            f"The user's exact current local date and time is: {local_time}\n"
            f"USAGE INSTRUCTION: Use this system time purely as passive background context "
            f"to understand the user's daily cycle. "
            f"Do NOT mention this time, do NOT say 'I see it is [time]', and do NOT force greetings "
            f"(like morning/night) on every message unless the user asks for the time or the current "
            f"time genuinely and naturally context-warrants it.\n"
        )

    # 5. Add custom personality if provided
    if custom_prompt:
        base_prompt += f"\n\n[USER CUSTOM PERSONALITY INSTRUCTIONS]\n{custom_prompt}\n"

    return base_prompt
