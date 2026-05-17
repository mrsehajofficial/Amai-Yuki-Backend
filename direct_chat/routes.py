from flask import Blueprint, request, jsonify
from datetime import datetime
from auth.routes import token_required
from db.database import get_creds_db, get_data_db

direct_chat_bp = Blueprint('direct_chat', __name__, url_prefix='/direct')

@direct_chat_bp.route('/search', methods=['GET'])
@token_required
def search_users(current_user):
    """
    Search for users by username to start a chat.
    Query Params:
        q (str): The search query (username)
    """
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'success': False, 'data': None, 'error': 'Search query is required'}), 400

    try:
        with get_creds_db() as conn:
            # We search for users matching the query, excluding the current user
            users = conn.execute(
                "SELECT id, username, full_name, email FROM users WHERE username LIKE ? AND id != ? LIMIT 20",
                (f'%{query}%', current_user['id'])
            ).fetchall()

        user_list = [dict(u) for u in users]
        return jsonify({'success': True, 'data': {'users': user_list}, 'error': None})

    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500

@direct_chat_bp.route('/send', methods=['POST'])
@token_required
def send_direct_message(current_user):
    """
    Send a message to another user.
    Body:
        receiver_id (int, required)
        content     (str, required)
    """
    data = request.get_json()
    receiver_id = data.get('receiver_id')
    content = data.get('content', '').strip()

    if not receiver_id or not content:
        return jsonify({'success': False, 'data': None, 'error': 'receiver_id and content are required'}), 400

    try:
        # Check if receiver exists
        with get_creds_db() as conn:
            receiver = conn.execute("SELECT id FROM users WHERE id = ?", (receiver_id,)).fetchone()
            if not receiver:
                return jsonify({'success': False, 'data': None, 'error': 'Receiver not found'}), 404

        # Save message to DATA_DB
        with get_data_db() as conn:
            cursor = conn.execute(
                "INSERT INTO direct_messages (sender_id, receiver_id, content) VALUES (?, ?, ?)",
                (current_user['id'], receiver_id, content)
            )
            msg_id = cursor.lastrowid
            conn.commit()

        # Trigger background summarization evaluation for both the sender and receiver.
        # Since peer-to-peer relationships involve active changes on both sides, both summaries
        # are updated asynchronously so that Yuki knows about this exchange when chatting with either.
        from memory.manager import check_and_trigger_direct_chat_summary
        check_and_trigger_direct_chat_summary(current_user['id'])
        check_and_trigger_direct_chat_summary(receiver_id)

        return jsonify({
            'success': True,
            'data': {
                'id': msg_id,
                'sender_id': current_user['id'],
                'receiver_id': receiver_id,
                'content': content,
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            },
            'error': None
        })

    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500

@direct_chat_bp.route('/history/<int:other_user_id>', methods=['GET'])
@token_required
def get_direct_history(current_user, other_user_id):
    """
    Fetch chat history between current user and another user.
    """
    try:
        with get_data_db() as conn:
            # 1. First, mark all unread messages from this sender to the current user as read (seen)
            conn.execute('''
                UPDATE direct_messages SET is_read = 1 
                WHERE receiver_id = ? AND sender_id = ? AND is_read = 0
            ''', (current_user['id'], other_user_id))
            conn.commit()

            # 2. Then, fetch the complete history with the updated read states!
            messages = conn.execute('''
                SELECT id, sender_id, receiver_id, content, timestamp, is_read, reaction
                FROM direct_messages
                WHERE (sender_id = ? AND receiver_id = ?)
                   OR (sender_id = ? AND receiver_id = ?)
                ORDER BY timestamp ASC
            ''', (current_user['id'], other_user_id, other_user_id, current_user['id'])).fetchall()

        message_list = [dict(m) for m in messages]
        return jsonify({'success': True, 'data': {'messages': message_list}, 'error': None})

    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500

@direct_chat_bp.route('/conversations', methods=['GET'])
@token_required
def get_conversations(current_user):
    """
    Returns a list of users the current user has chatted with,
    along with the last message and unread count.
    """
    try:
        # Get list of unique chat partners and their latest message details
        with get_data_db() as conn:
            convos = conn.execute('''
                WITH LastMessages AS (
                    SELECT 
                        id,
                        CASE WHEN sender_id = ? THEN receiver_id ELSE sender_id END as other_user_id,
                        content,
                        timestamp,
                        ROW_NUMBER() OVER (
                            PARTITION BY CASE WHEN sender_id = ? THEN receiver_id ELSE sender_id END 
                            ORDER BY timestamp DESC
                        ) as rn
                    FROM direct_messages
                    WHERE sender_id = ? OR receiver_id = ?
                )
                SELECT other_user_id, content as last_message, timestamp
                FROM LastMessages
                WHERE rn = 1
                ORDER BY timestamp DESC
            ''', (current_user['id'], current_user['id'], current_user['id'], current_user['id'])).fetchall()

        if not convos:
            return jsonify({'success': True, 'data': {'conversations': []}, 'error': None})

        # Fetch unread counts separately for clarity
        with get_data_db() as conn:
            unread_counts = conn.execute('''
                SELECT sender_id, COUNT(*) as count
                FROM direct_messages
                WHERE receiver_id = ? AND is_read = 0
                GROUP BY sender_id
            ''', (current_user['id'],)).fetchall()
            unread_map = {row['sender_id']: row['count'] for row in unread_counts}

        other_user_ids = [c['other_user_id'] for c in convos]
        
        # Fetch user details from CREDS_DB
        with get_creds_db() as conn:
            placeholders = ','.join(['?'] * len(other_user_ids))
            users = conn.execute(
                f"SELECT id, username, full_name, email FROM users WHERE id IN ({placeholders})",
                tuple(other_user_ids)
            ).fetchall()
            user_map = {u['id']: {'username': u['username'], 'full_name': u['full_name'], 'email': u['email']} for u in users}

        results = []
        for c in convos:
            uid = c['other_user_id']
            user_info = user_map.get(uid, {'username': 'Unknown User', 'full_name': None, 'email': ''})
            results.append({
                'user_id': uid,
                'username': user_info['username'],
                'full_name': user_info['full_name'],
                'email': user_info['email'],
                'last_message': c['last_message'],
                'timestamp': c['timestamp'],
                'unread_count': unread_map.get(uid, 0)
            })

        return jsonify({'success': True, 'data': {'conversations': results}, 'error': None})

    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500

@direct_chat_bp.route('/react', methods=['POST'])
@token_required
def react_to_message(current_user):
    """
    React to a direct message, or clear a reaction.
    Body:
        message_id (int, required)
        reaction   (str, optional) - Emoji character, or null/empty to clear.
    """
    data = request.get_json()
    message_id = data.get('message_id')
    reaction = data.get('reaction', '').strip() or None

    if not message_id:
        return jsonify({'success': False, 'data': None, 'error': 'message_id is required'}), 400

    try:
        with get_data_db() as conn:
            # Verify the message exists and belongs to the active chat
            msg = conn.execute(
                "SELECT sender_id, receiver_id FROM direct_messages WHERE id = ?",
                (message_id,)
            ).fetchone()

            if not msg:
                return jsonify({'success': False, 'data': None, 'error': 'Message not found'}), 404

            if msg['sender_id'] != current_user['id'] and msg['receiver_id'] != current_user['id']:
                return jsonify({'success': False, 'data': None, 'error': 'Unauthorized to react to this message'}), 403

            # Update the reaction in the database
            conn.execute(
                "UPDATE direct_messages SET reaction = ? WHERE id = ?",
                (reaction, message_id)
            )
            conn.commit()

        return jsonify({
            'success': True,
            'data': {
                'message_id': message_id,
                'reaction': reaction
            },
            'error': None
        })

    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500


@direct_chat_bp.route('/clear/<int:other_user_id>', methods=['DELETE'])
@token_required
def clear_direct_chat(current_user, other_user_id):
    """
    Wipes all direct messages between the current user and another user.
    """
    try:
        with get_data_db() as conn:
            conn.execute('''
                DELETE FROM direct_messages 
                WHERE (sender_id = ? AND receiver_id = ?)
                   OR (sender_id = ? AND receiver_id = ?)
            ''', (current_user['id'], other_user_id, other_user_id, current_user['id']))
            conn.commit()

        # Force a background social memory cache update or deletion for both users.
        # This keeps our custom system prompts clean from stale, deleted message records.
        from memory.manager import force_direct_chat_summary
        force_direct_chat_summary(current_user['id'])
        force_direct_chat_summary(other_user_id)

        return jsonify({'success': True, 'data': {'message': 'Chat history cleared successfully'}, 'error': None})

    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500
