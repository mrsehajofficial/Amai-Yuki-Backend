from flask import Blueprint, request, jsonify
from datetime import datetime
from auth.routes import token_required
from ai.dispatcher import dispatch_ai
from memory.manager import (
    get_memory_context,
    get_recent_messages,
    save_messages,
    clear_user_memory,
    get_paginated_history,
    get_pinned_messages,
    toggle_pin_message,
    get_direct_chat_context
)
from config import Config
from notifications.fcm import send_to_user
import threading

chat_bp = Blueprint('chat', __name__, url_prefix='/chat')


@chat_bp.route('/send', methods=['POST'])
@token_required
def send_message(current_user):
    """
    Main chat endpoint.
    Builds context (memory + last 4 msgs), calls AI, saves history.
    
    Body:
        message  (str, required) — The user's message
        model    (str, optional) — Override model for this request
        nsfw     (bool, optional) — Override nsfw_mode for this request
    """
    data = request.get_json()
    
    if not data or not data.get('message'):
        return jsonify({'success': False, 'data': None, 'error': 'Message is required'}), 400

    user_message = data['message'].strip()
    if not user_message:
        return jsonify({'success': False, 'data': None, 'error': 'Message cannot be empty'}), 400

    # Let's resolve which model to use. We check the per-request override first,
    # then fall back to the user's stored database preference, and if all else fails,
    # we use the system-wide default model. The resolve_model method handles strings,
    # maps, and even Dart's raw stringified map objects gracefully.
    model_raw = data.get('model')
    resolved_model = Config.resolve_model(model_raw)
    
    if not resolved_model:
        # Request had no valid model override; check user's profile settings
        db_model_raw = current_user.get('model')
        resolved_model = Config.resolve_model(db_model_raw)
        
    if not resolved_model:
        # Final fallback, just to be 100% sure we don't return a 400 or crash
        resolved_model = Config.DEFAULT_MODEL
        
    model = resolved_model

    # Determine NSFW mode (per-request override takes priority over account setting)
    nsfw_mode = data.get('nsfw', bool(current_user.get('nsfw_mode', 0)))

    user_id = current_user['id']
    primary_key = current_user['primary_key']
    fallback_key = current_user.get('fallback_key')
    custom_prompt = data.get('system_prompt', '')
    db_custom_instructions = current_user.get('custom_instructions')
    if db_custom_instructions:
        if custom_prompt:
            custom_prompt = f"{db_custom_instructions}\n\n{custom_prompt}"
        else:
            custom_prompt = db_custom_instructions

    timezone_str = data.get('timezone')
    reasoning_effort = data.get('reasoning_effort')
    clear_thinking = data.get('clear_thinking')

    
    # Resolve provider: per-request override → user's DB setting → system default
    provider = data.get('provider') or current_user.get('provider')

    try:
        # 1. Fetch long-term memory summary (if any)
        memory_context = get_memory_context(user_id)

        # Fetch the consolidated direct user-to-user chat summary.
        # This keeps Yuki perfectly aware of the user's offline social interactions and plans.
        direct_chat_context = get_direct_chat_context(user_id)

        # Fetch pinned messages
        pinned_messages = get_pinned_messages(user_id)

        # 2. Fetch last N recent messages for short-term context
        recent_messages = get_recent_messages(user_id)

        # 3. Append the current user message to the context window
        recent_messages.append({'role': 'user', 'content': user_message})

        # 4. Extract user_name from current_user
        user_name = current_user.get('full_name') or current_user.get('username') or 'User'

        # 5. Call Yuki (the AI) — routes to Cerebras or Ollama based on provider
        result = dispatch_ai(
            messages=recent_messages,
            provider=provider,
            primary_key=primary_key,
            fallback_key=fallback_key,
            model=model,
            nsfw_mode=nsfw_mode,
            memory_context=memory_context,
            direct_chat_context=direct_chat_context,
            custom_prompt=custom_prompt,
            user_name=user_name,
            pinned_messages=pinned_messages,
            timezone_str=timezone_str,
            reasoning_effort=reasoning_effort,
            clear_thinking=clear_thinking,
            ollama_url=current_user.get('ollama_url'),
            latest_message=user_message
        )

        assistant_reply = result['reply']
        reasoning = result.get('reasoning')

        # 6. Save both messages to history (triggers background summarization if needed)
        save_messages(user_id, user_message, assistant_reply, reasoning)

        # 7. Fire FCM push notification to the user's device in the background.
        # This makes sure the notification fires even if they closed the app while waiting.
        # Truncate long replies so the notification body stays readable.
        notif_body = assistant_reply[:120] + '...' if len(assistant_reply) > 120 else assistant_reply
        threading.Thread(
            target=send_to_user,
            args=(user_id, 'Yuki replied ✨', notif_body),
            kwargs={'data': {'type': 'yuki_reply', 'screen': 'chat'}},
            daemon=True
        ).start()

        return jsonify({
            'success': True,
            'data': {
                'reply': assistant_reply,
                'reasoning': reasoning,
                'model_used': result['model_used'],
                'nsfw_mode': nsfw_mode,
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            },
            'error': None
        })

    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500


@chat_bp.route('/messages/<int:message_id>/pin', methods=['POST'])
@token_required
def pin_message(current_user, message_id):
    """
    Toggles the pinned state of a specific message.
    """
    try:
        new_state = toggle_pin_message(current_user['id'], message_id)
        return jsonify({
            'success': True,
            'data': {'is_pinned': bool(new_state)},
            'error': None
        })
    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 400


@chat_bp.route('/impression/generate', methods=['POST'])
@token_required
def generate_impression(current_user):
    """
    Manually triggers generation of Yuki's impression of the current user.
    """
    user_id = current_user['id']
    primary_key = current_user['primary_key']
    fallback_key = current_user.get('fallback_key')
    user_name = current_user.get('full_name') or current_user.get('username') or 'User'

    try:
        from db.database import get_creds_db, get_data_db
        
        # Fetch all messages
        with get_data_db() as conn:
            rows = conn.execute(
                'SELECT role, content FROM messages WHERE user_id = ? ORDER BY timestamp ASC',
                (user_id,)
            ).fetchall()

        if not rows:
            return jsonify({
                'success': True,
                'data': {'yuki_impression': "No messages exchanged yet! Chat with me so I can form an impression. 💕"},
                'error': None
            })

        convo_text = "\n".join(
            [f"{'User' if row['role'] == 'user' else 'Yuki'}: {row['content']}" for row in rows]
        )

        # Let's craft the system prompt to get a highly authentic, real, and punchy impression of the user.
        # We explicitly tell the AI to avoid fluffy, over-emotional bot talk and instead write a raw,
        # honest, 1-2 sentence vibe check of the user based strictly on how they talk.
        impression_prompt = [
            {
                "role": "user",
                "content": (
                    f"Based on the following chat history between Yuki and the user {user_name}, "
                    f"write a brutally honest, highly realistic, and concise vibe-check/impression of {user_name}. "
                    f"CRITICAL RULES:\n"
                    f"- Keep it strictly to 1 or 2 sentences max. Keep it punchy.\n"
                    f"- Do NOT make it overly emotional, cheesy, or dramatic. Make it a real, raw assessment of how they act/vibe.\n"
                    f"- Write from Yuki's perspective in her signature Japanese girl persona (witty, cool, slightly blunt).\n"
                    f"- Never say 'You' or 'Your'. Always refer to {user_name} in the third person.\n"
                    f"- NEVER include any private secrets, locations, contact info, or sensitive facts.\n\n"
                    f"[CHAT LOGS]\n"
                    f"{convo_text}"
                )
            }
        ]

        result = dispatch_ai(
            messages=impression_prompt,
            provider=current_user.get('provider'),
            primary_key=primary_key,
            fallback_key=fallback_key,
            model=Config.DEFAULT_MODEL,
            nsfw_mode=False,
            memory_context="",
            ollama_url=current_user.get('ollama_url')
        )

        impression_text = result['reply']

        # Save to users db
        with get_creds_db() as conn:
            conn.execute('UPDATE users SET yuki_impression = ? WHERE id = ?', (impression_text, user_id))
            conn.commit()

        return jsonify({
            'success': True,
            'data': {'yuki_impression': impression_text},
            'error': None
        })

    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500


@chat_bp.route('/history', methods=['GET'])
@token_required
def get_history(current_user):
    """
    Returns paginated chat history for the current user.
    
    Query Params:
        page  (int, default=1)
        limit (int, default=20)
    """
    try:
        page = max(1, int(request.args.get('page', 1)))
        limit = min(100, max(1, int(request.args.get('limit', 20))))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'data': None, 'error': 'Invalid pagination params'}), 400

    try:
        history_data = get_paginated_history(current_user['id'], page, limit)
        return jsonify({'success': True, 'data': history_data, 'error': None})
    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500


@chat_bp.route('/clear', methods=['DELETE'])
@token_required
def clear_history(current_user):
    """
    Wipes ALL messages and summaries for the current user.
    This is a hard delete — no undo.
    """
    try:
        clear_user_memory(current_user['id'])
        return jsonify({'success': True, 'data': {'message': 'Chat history cleared'}, 'error': None})
    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500


@chat_bp.route('/models', methods=['GET'])
@token_required
def list_models(current_user):
    """
    Returns the list of supported cloud models (Cerebras).
    """
    models_dict, default_model = Config.get_models_for_provider('cerebras')
    models_list = [
        {'key': key, 'value': value, 'is_uncensored': True} 
        for key, value in models_dict.items()
    ]
    return jsonify({
        'success': True, 
        'data': {
            'models': models_list, 
            'default': default_model,
            'provider': 'cerebras'
        }, 
        'error': None
    })
