import threading
from datetime import datetime, timedelta
from db.database import get_data_db
from config import Config

def get_memory_context(user_id):
    """
    Fetches the latest summary for a user.
    This is injected into the system prompt as [MEMORY CONTEXT].
    Returns an empty string if no summary exists yet.
    """
    with get_data_db() as conn:
        summary = conn.execute(
            'SELECT summary_text FROM summaries WHERE user_id = ? ORDER BY created_at DESC LIMIT 1',
            (user_id,)
        ).fetchone()

    return summary['summary_text'] if summary else ""


def get_recent_messages(user_id):
    """
    Fetches the last N messages (defined in config) for this user.
    Returns a list of dicts ready to be passed to the AI API.
    """
    with get_data_db() as conn:
        rows = conn.execute(
            '''
            SELECT role, content FROM messages
            WHERE user_id = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            ''',
            (user_id, Config.MAX_HISTORY_MESSAGES)
        ).fetchall()

    # Reverse so they're in chronological order (oldest → newest)
    messages = [{'role': row['role'], 'content': row['content']} for row in reversed(rows)]
    return messages


def save_messages(user_id, user_message, assistant_reply):
    """
    Saves both the user's message and Yuki's reply into the data.db.
    After saving, checks if we've hit the summarization threshold.
    """
    with get_data_db() as conn:
        # We need distinct timestamps to ensure correct ordering when fetching from DB.
        # If they are identical, the sort order becomes non-deterministic.
        now = datetime.utcnow()
        user_ts = now.isoformat()
        # Shift assistant by a tiny bit to guarantee it follows the user message
        assistant_ts = (now + timedelta(milliseconds=10)).isoformat()
        
        conn.execute(
            'INSERT INTO messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)',
            (user_id, 'user', user_message, user_ts)
        )
        conn.execute(
            'INSERT INTO messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)',
            (user_id, 'assistant', assistant_reply, assistant_ts)
        )
        conn.commit()

        # Count total messages for this user
        count_row = conn.execute(
            'SELECT COUNT(*) as count FROM messages WHERE user_id = ?',
            (user_id,)
        ).fetchone()
        total = count_row['count']

    # Every MESSAGES_BEFORE_SUMMARY messages, fire a background summarization
    # +1 accounts for the message we just saved (the assistant reply)
    if total % Config.MESSAGES_BEFORE_SUMMARY == 0:
        thread = threading.Thread(
            target=_run_summarization,
            args=(user_id, total),
            daemon=True
        )
        thread.start()


def _run_summarization(user_id, message_count):
    """
    Background job: fetches all messages for the user and summarizes them.
    Calls the AI to produce a tight, compressed memory summary.
    Saves it to the summaries table.
    
    NOTE: This runs in a background thread — no request context available here.
    We import the AI client and use the user's keys directly.
    """
    try:
        from db.database import get_creds_db
        from ai.client import call_ai

        # Get user's API keys, username/full_name, and current nsfw mode
        with get_creds_db() as conn:
            user = conn.execute(
                'SELECT username, full_name, primary_key, fallback_key, nsfw_mode FROM users WHERE id = ?',
                (user_id,)
            ).fetchone()

        if not user:
            return

        # Fetch all messages to summarize
        with get_data_db() as conn:
            rows = conn.execute(
                'SELECT role, content FROM messages WHERE user_id = ? ORDER BY timestamp ASC',
                (user_id,)
            ).fetchall()

        if not rows:
            return

        # Build conversation text for the summarizer
        convo_text = "\n".join(
            [f"{'User' if row['role'] == 'user' else 'Yuki'}: {row['content']}" for row in rows]
        )

        # Ask the AI to produce a concise memory summary
        summary_prompt = [
            {
                "role": "user",
                "content": (
                    f"The following is a conversation between Yuki and the user. "
                    f"Please create a concise, dense memory summary that captures key facts, "
                    f"preferences, important topics discussed, and anything Yuki should remember "
                    f"about the user for future conversations. Keep it under 300 words.\n\n"
                    f"{convo_text}"
                )
            }
        ]

        result = call_ai(
            messages=summary_prompt,
            primary_key=user['primary_key'],
            fallback_key=user['fallback_key'],
            model=Config.DEFAULT_MODEL,
            nsfw_mode=False,  # Always use SFW mode for summarization
            memory_context=""  # No memory needed for meta-summarization
        )

        # Generate Yuki's Impression of the user
        user_name = user['full_name'] or user['username'] or 'User'
        impression_prompt = [
            {
                "role": "user",
                "content": (
                    f"Based on the following chat history between Yuki and the user {user_name}, "
                    f"please write a short, highly engaging paragraph (2-3 sentences max) detailing Yuki's impression "
                    f"of {user_name}. "
                    f"CRITICAL: Do NOT include any of their private personal secrets, specifics, contact info, "
                    f"or sensitive facts they shared (like where they live, work, names of friends, etc.). "
                    f"Write it purely from Yuki's perspective in her signature Japanese girl persona, "
                    f"describing what she thinks of their personality vibe, their energy, or how much she enjoys talking to them.\n\n"
                    f"{convo_text}"
                )
            }
        ]

        result_impression = call_ai(
            messages=impression_prompt,
            primary_key=user['primary_key'],
            fallback_key=user['fallback_key'],
            model=Config.DEFAULT_MODEL,
            nsfw_mode=False,
            memory_context=""
        )

        # Save the new summary
        with get_data_db() as conn:
            conn.execute(
                'INSERT INTO summaries (user_id, summary_text, message_count, created_at) VALUES (?, ?, ?, ?)',
                (user_id, result['reply'], message_count, datetime.utcnow().isoformat())
            )
            conn.commit()

        # Save the impression to the credentials db
        with get_creds_db() as conn:
            conn.execute(
                'UPDATE users SET yuki_impression = ? WHERE id = ?',
                (result_impression['reply'], user_id)
            )
            conn.commit()

    except Exception as e:
        # Silently log — this is background, don't crash the main thread
        print(f"[Memory] Summarization/Impression failed for user {user_id}: {e}")



def get_direct_chat_context(user_id):
    """
    Fetches the pre-summarized peer-to-peer direct chat context for the active user.
    This keeps the main AI conversation cycle highly responsive since the summary
    is fully cached and doesn't require a runtime LLM-based summarization pass.
    """
    with get_data_db() as conn:
        row = conn.execute(
            'SELECT summary_text FROM direct_chat_summaries WHERE user_id = ? LIMIT 1',
            (user_id,)
        ).fetchone()
    return row['summary_text'] if row else ""


def check_and_trigger_direct_chat_summary(user_id):
    """
    Evaluates whether the user's direct messages have changed enough to trigger
    a background summarization run. Keeps the system fast, cheap, and safe from
    hitting API rate limits by enforcing a strict update interval.
    """
    with get_data_db() as conn:
        # Determine current total number of peer-to-peer interactions
        row = conn.execute(
            'SELECT COUNT(*) as count FROM direct_messages WHERE sender_id = ? OR receiver_id = ?',
            (user_id, user_id)
        ).fetchone()
        total = row['count'] if row else 0

        # Retrieve the count at which we last summarized this user's interactions
        sum_row = conn.execute(
            'SELECT message_count FROM direct_chat_summaries WHERE user_id = ?',
            (user_id,)
        ).fetchone()
        last_count = sum_row['message_count'] if sum_row else 0

    # Trigger a background summary if:
    # 1. They have chats, but we have never summarized them (first contact).
    # 2. They have accumulated at least Config.MESSAGES_BEFORE_SUMMARY new messages.
    if total > 0 and (last_count == 0 or (total - last_count) >= Config.MESSAGES_BEFORE_SUMMARY):
        thread = threading.Thread(
            target=summarize_direct_chats_bg,
            args=(user_id, total),
            daemon=True
        )
        thread.start()


def force_direct_chat_summary(user_id):
    """
    Forces an immediate background re-summarization. Useful when the user deletes
    specific threads, requiring us to instantly invalidate and refresh our cached state.
    """
    with get_data_db() as conn:
        row = conn.execute(
            'SELECT COUNT(*) as count FROM direct_messages WHERE sender_id = ? OR receiver_id = ?',
            (user_id, user_id)
        ).fetchone()
        total = row['count'] if row else 0

    if total == 0:
        # User has no direct chats left; clear the cache completely.
        with get_data_db() as conn:
            conn.execute('DELETE FROM direct_chat_summaries WHERE user_id = ?', (user_id,))
            conn.commit()
    else:
        # Spin up a background thread to update the remaining social context.
        thread = threading.Thread(
            target=summarize_direct_chats_bg,
            args=(user_id, total),
            daemon=True
        )
        thread.start()


def summarize_direct_chats_bg(user_id, message_count):
    """
    Asynchronous worker that fetches all direct user-to-user messages involving the target user,
    groups them cleanly by interaction partner, builds a highly clear conversation log,
    and prompts the LLM to write a high-fidelity relationship & activity summary.
    """
    try:
        from db.database import get_creds_db, get_data_db
        from ai.client import call_ai

        # 1. Fetch user credentials and details to locate API keys and format placeholders.
        with get_creds_db() as conn:
            user = conn.execute(
                'SELECT username, full_name, primary_key, fallback_key FROM users WHERE id = ?',
                (user_id,)
            ).fetchone()

        if not user:
            return

        user_name = user['full_name'] or user['username'] or 'User'

        # 2. Fetch all direct messages in chronological order.
        with get_data_db() as conn:
            rows = conn.execute(
                '''
                SELECT sender_id, receiver_id, content, timestamp 
                FROM direct_messages 
                WHERE sender_id = ? OR receiver_id = ? 
                ORDER BY timestamp ASC
                ''',
                (user_id, user_id)
            ).fetchall()

        if not rows:
            # If no chats exist anymore, clean up cache.
            with get_data_db() as conn:
                conn.execute('DELETE FROM direct_chat_summaries WHERE user_id = ?', (user_id,))
                conn.commit()
            return

        # 3. Gather unique partner IDs so we can map their IDs to actual names/usernames.
        other_user_ids = set()
        for r in rows:
            other_user_ids.add(r['sender_id'] if r['sender_id'] != user_id else r['receiver_id'])

        # 4. Resolve partner names.
        other_users_map = {}
        if other_user_ids:
            with get_creds_db() as conn:
                placeholders = ','.join(['?'] * len(other_user_ids))
                users = conn.execute(
                    f"SELECT id, username, full_name FROM users WHERE id IN ({placeholders})",
                    tuple(other_user_ids)
                ).fetchall()
                for u in users:
                    other_users_map[u['id']] = u['full_name'] or u['username']

        # 5. Group conversations into distinct structured channels for the model.
        conversations = {}
        for r in rows:
            partner_id = r['sender_id'] if r['sender_id'] != user_id else r['receiver_id']
            partner_name = other_users_map.get(partner_id, f"User_{partner_id}")
            if partner_name not in conversations:
                conversations[partner_name] = []
            
            sender_name = user_name if r['sender_id'] == user_id else partner_name
            conversations[partner_name].append(f"{sender_name}: {r['content']}")

        # 6. Format the dialogue blocks, keeping at most the last 30 messages per thread for speed.
        convo_blocks = []
        for partner_name, msgs in conversations.items():
            recent_msgs = msgs[-30:]
            convo_text = "\n".join(recent_msgs)
            convo_blocks.append(f"Conversation with {partner_name}:\n{convo_text}")

        all_convos_text = "\n\n".join(convo_blocks)

        # 7. Query the AI to build a highly dense and factual digest of these peer-to-peer activities.
        summary_prompt = [
            {
                "role": "user",
                "content": (
                    f"The following are recent direct message chat logs between the user ({user_name}) and other people on our system:\n\n"
                    f"{all_convos_text}\n\n"
                    f"Please write a highly concise, dense, factual summary of the user's social interactions, current plans, agreements, "
                    f"shared secrets, and general relationship dynamics with these users.\n"
                    f"Keep it under 250 words. Write purely in a factual, third-person perspective. Amai Yuki (the AI assistant) will read this "
                    f"context to naturally bring up or refer to their friends and peer-to-peer activities during chat interactions. "
                    f"DO NOT include any introductory or meta-commentary like 'In these conversations...'. Write the summary directly."
                )
            }
        ]

        result = call_ai(
            messages=summary_prompt,
            primary_key=user['primary_key'],
            fallback_key=user['fallback_key'],
            model=Config.DEFAULT_MODEL,
            nsfw_mode=False,
            memory_context=""
        )

        summary_text = result['reply'].strip()

        # 8. Save the summarized context in our data store.
        with get_data_db() as conn:
            conn.execute(
                '''
                REPLACE INTO direct_chat_summaries (user_id, summary_text, message_count, updated_at) 
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ''',
                (user_id, summary_text, message_count)
            )
            conn.commit()

        print(f"[DirectChatMemory] Successfully summarized direct chats for user {user_id} ({user_name})")

    except Exception as e:
        print(f"[DirectChatMemory] Failed to summarize direct chats for user {user_id}: {e}")


def clear_user_memory(user_id):
    """
    Wipes all messages, chat history summaries, and direct chat social memories
    for the specified user. This represents a complete fresh start (hard reset).
    """
    with get_data_db() as conn:
        conn.execute('DELETE FROM messages WHERE user_id = ?', (user_id,))
        conn.execute('DELETE FROM summaries WHERE user_id = ?', (user_id,))
        conn.execute('DELETE FROM direct_chat_summaries WHERE user_id = ?', (user_id,))
        conn.commit()

def get_pinned_messages(user_id):
    """
    Fetches all pinned messages for the user.
    """
    with get_data_db() as conn:
        rows = conn.execute(
            '''
            SELECT role, content FROM messages
            WHERE user_id = ? AND is_pinned = 1
            ORDER BY timestamp ASC
            ''',
            (user_id,)
        ).fetchall()
    return [{'role': row['role'], 'content': row['content']} for row in rows]

def toggle_pin_message(user_id, message_id):
    """
    Toggles the is_pinned state of a specific message.
    Returns the new state.
    """
    with get_data_db() as conn:
        msg = conn.execute('SELECT is_pinned FROM messages WHERE id = ? AND user_id = ?', (message_id, user_id)).fetchone()
        if not msg:
            raise Exception("Message not found or unauthorized")
        
        new_state = 1 if msg['is_pinned'] == 0 else 0
        conn.execute('UPDATE messages SET is_pinned = ? WHERE id = ?', (new_state, message_id))
        conn.commit()
        return new_state

def get_paginated_history(user_id, page=1, limit=20):
    """
    Returns paginated chat history for a user.
    Ordered newest first.
    """
    offset = (page - 1) * limit
    
    with get_data_db() as conn:
        rows = conn.execute(
            '''
            SELECT id, role, content, timestamp, is_pinned FROM messages
            WHERE user_id = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT ? OFFSET ?
            ''',
            (user_id, limit, offset)
        ).fetchall()
        
        total_count = conn.execute(
            'SELECT COUNT(*) as count FROM messages WHERE user_id = ?',
            (user_id,)
        ).fetchone()['count']

    messages = [dict(row) for row in rows]
    total_pages = (total_count + limit - 1) // limit  # Ceiling division

    return {
        "messages": messages,
        "pagination": {
            "page": page,
            "limit": limit,
            "total_messages": total_count,
            "total_pages": total_pages
        }
    }


def update_all_user_impressions():
    """
    Runs daily (usually at 3 AM) to refresh impressions for all active users.
    """
    print("[Scheduler] Starting daily user impression updates...")
    try:
        from db.database import get_creds_db
        from ai.client import call_ai

        # Fetch all active users
        with get_creds_db() as conn:
            users = conn.execute('SELECT id, username, full_name, primary_key, fallback_key FROM users').fetchall()

        for u in users:
            user_id = u['id']
            primary_key = u['primary_key']
            fallback_key = u.get('fallback_key')
            user_name = u['full_name'] or u['username'] or 'User'

            # Fetch all messages for this user
            with get_data_db() as conn:
                rows = conn.execute(
                    'SELECT role, content FROM messages WHERE user_id = ? ORDER BY timestamp ASC',
                    (user_id,)
                ).fetchall()

            if not rows:
                continue

            convo_text = "\n".join(
                [f"{'User' if r['role'] == 'user' else 'Yuki'}: {r['content']}" for r in rows]
            )

            impression_prompt = [
                {
                    "role": "user",
                    "content": (
                        f"Based on the following chat history between Yuki and the user {user_name}, "
                        f"please write a short, highly engaging paragraph (2-3 sentences max) detailing Yuki's impression "
                        f"of {user_name}. "
                        f"CRITICAL: Do NOT include any of their private personal secrets, specifics, contact info, "
                        f"or sensitive facts they shared (like where they live, work, names of friends, etc.). "
                        f"Write it purely from Yuki's perspective in her signature Japanese girl persona, "
                        f"describing what she thinks of their personality vibe, their energy, or how much she enjoys talking to them.\n\n"
                        f"{convo_text}"
                    )
                }
            ]

            try:
                result = call_ai(
                    messages=impression_prompt,
                    primary_key=primary_key,
                    fallback_key=fallback_key,
                    model=Config.DEFAULT_MODEL,
                    nsfw_mode=False,
                    memory_context=""
                )

                # Save the new impression
                with get_creds_db() as conn:
                    conn.execute('UPDATE users SET yuki_impression = ? WHERE id = ?', (result['reply'], user_id))
                    conn.commit()
                print(f"[Scheduler] Updated impression for user {user_name}")
            except Exception as e:
                print(f"[Scheduler] Failed to update impression for user {user_name}: {e}")

    except Exception as e:
        print(f"[Scheduler] Daily impression update failed: {e}")


def start_scheduler():
    """
    Spawns the background daemon thread to run the daily impression updates at 3 AM.
    """
    import time
    
    def run_daily_impression_scheduler():
        print("[Scheduler] Daily impression scheduler thread started.")
        last_run_date = None
        while True:
            try:
                now = datetime.now()
                # Check if it is 3 AM and we haven't run today yet
                if now.hour == 3 and now.minute == 0 and last_run_date != now.date():
                    last_run_date = now.date()
                    thread = threading.Thread(target=update_all_user_impressions, daemon=True)
                    thread.start()
            except Exception as e:
                print(f"[Scheduler] Error in sleep loop: {e}")
            time.sleep(30) # Check every 30 seconds

    scheduler_thread = threading.Thread(target=run_daily_impression_scheduler, daemon=True)
    scheduler_thread.start()
