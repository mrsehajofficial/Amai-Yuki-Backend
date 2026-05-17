from flask import Blueprint, request, jsonify
from datetime import datetime
from auth.routes import token_required
from ai.client import call_ai
from memory.manager import (
    get_memory_context,
    get_recent_messages,
    save_messages,
    clear_user_memory,
    get_paginated_history,
    get_pinned_messages,
    toggle_pin_message
)
from config import Config

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

    # Determine which model to use (per-request override or user's stored preference)
    model = data.get('model', current_user.get('model', Config.DEFAULT_MODEL))
    if model not in Config.MODELS.values():
        return jsonify({'success': False, 'data': None, 'error': 'Invalid model specified'}), 400

    # Determine NSFW mode (per-request override takes priority over account setting)
    nsfw_mode = data.get('nsfw', bool(current_user.get('nsfw_mode', 0)))

    user_id = current_user['id']
    primary_key = current_user['primary_key']
    fallback_key = current_user.get('fallback_key')
    custom_prompt = data.get('system_prompt', '')
    timezone_str = data.get('timezone')

    try:
        # 1. Fetch long-term memory summary (if any)
        memory_context = get_memory_context(user_id)

        # Fetch pinned messages
        pinned_messages = get_pinned_messages(user_id)

        # 2. Fetch last N recent messages for short-term context
        recent_messages = get_recent_messages(user_id)

        # 3. Append the current user message to the context window
        recent_messages.append({'role': 'user', 'content': user_message})

        # 4. Extract user_name from current_user
        user_name = current_user.get('full_name') or current_user.get('username') or 'User'

        # 5. Call Yuki (the AI)
        result = call_ai(
            messages=recent_messages,
            primary_key=primary_key,
            fallback_key=fallback_key,
            model=model,
            nsfw_mode=nsfw_mode,
            memory_context=memory_context,
            custom_prompt=custom_prompt,
            user_name=user_name,
            pinned_messages=pinned_messages,
            timezone_str=timezone_str
        )

        assistant_reply = result['reply']

        # 6. Save both messages to history (triggers background summarization if needed)
        save_messages(user_id, user_message, assistant_reply)

        return jsonify({
            'success': True,
            'data': {
                'reply': assistant_reply,
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
                    f"Never use 'You' or 'Your'. Always Use the username {user_name}"
                )
            }
        ]

        result = call_ai(
            messages=impression_prompt,
            primary_key=primary_key,
            fallback_key=fallback_key,
            model=Config.DEFAULT_MODEL,
            nsfw_mode=False,
            memory_context=""
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
    Returns the list of supported models.
    Useful for Flutter to populate a model picker.
    """
    models_list = [
        {'key': key, 'value': value} 
        for key, value in Config.MODELS.items()
    ]
    return jsonify({'success': True, 'data': {'models': models_list, 'default': Config.DEFAULT_MODEL}, 'error': None})
