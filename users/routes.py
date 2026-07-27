from flask import Blueprint, jsonify
from auth.routes import token_required
from db.database import get_creds_db
from datetime import datetime, timedelta

users_bp = Blueprint('users', __name__, url_prefix='/users')

@users_bp.route('/list', methods=['GET'])
@token_required
def list_users(current_user):
    """
    Returns a list of all users and their online status.
    Users are considered 'online' if they've been active in the last 2 minutes.
    """
    try:
        with get_creds_db() as conn:
            # Fetch all users except the current one
            users = conn.execute(
                'SELECT id, username, full_name, email, profile_pic, yuki_impression, last_seen, tag, custom_instructions FROM users WHERE id != ?',
                (current_user['id'],)
            ).fetchall()

            # Fetch current user's favorites
            favs = conn.execute(
                'SELECT favorite_user_id FROM favorites WHERE user_id = ?',
                (current_user['id'],)
            ).fetchall()
            fav_ids = {f['favorite_user_id'] for f in favs}

        now = datetime.utcnow()
        user_list = []
        
        for u in users:
            try:
                if not u['last_seen']:
                    last_seen = datetime.min
                else:
                    try:
                        last_seen = datetime.strptime(u['last_seen'], '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        try:
                            last_seen = datetime.strptime(u['last_seen'], '%Y-%m-%d %H:%M:%S.%f')
                        except:
                            last_seen = datetime.min
            except (ValueError, TypeError):
                last_seen = datetime.min

            is_online = (now - last_seen) < timedelta(minutes=2)
            
            user_list.append({
                'id': u['id'],
                'username': u['username'],
                'full_name': u['full_name'],
                'email': u['email'],
                'profile_pic': u['profile_pic'],
                'tag': u['tag'] or ('dev' if u['username'].lower() == 'sehaj' else 'user'),
                'custom_instructions': u['custom_instructions'] or '',
                'yuki_impression': u['yuki_impression'] or "No impression recorded yet.",
                'is_online': is_online,
                'last_seen': u['last_seen'],
                'is_favorite': u['id'] in fav_ids
            })

        return jsonify({'success': True, 'data': {'users': user_list}, 'error': None})


    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500


@users_bp.route('/favorites', methods=['GET'])
@token_required
def get_favorites(current_user):
    """
    Returns only the favorited users for the current logged-in user.
    """
    try:
        with get_creds_db() as conn:
            # Join favorites with users to get favorite user details
            users = conn.execute('''
                SELECT u.id, u.username, u.full_name, u.email, u.profile_pic, u.yuki_impression, u.last_seen 
                FROM favorites f
                JOIN users u ON f.favorite_user_id = u.id
                WHERE f.user_id = ?
            ''', (current_user['id'],)).fetchall()

        now = datetime.utcnow()
        fav_list = []
        
        for u in users:
            try:
                if not u['last_seen']:
                    last_seen = datetime.min
                else:
                    try:
                        last_seen = datetime.strptime(u['last_seen'], '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        try:
                            last_seen = datetime.strptime(u['last_seen'], '%Y-%m-%d %H:%M:%S.%f')
                        except:
                            last_seen = datetime.min
            except (ValueError, TypeError):
                last_seen = datetime.min

            is_online = (now - last_seen) < timedelta(minutes=2)
            
            fav_list.append({
                'id': u['id'],
                'username': u['username'],
                'full_name': u['full_name'],
                'email': u['email'],
                'profile_pic': u['profile_pic'],
                'yuki_impression': u['yuki_impression'] or "No impression recorded yet. Keep chatting with Yuki so she gets to know you! 💕",
                'is_online': is_online,
                'last_seen': u['last_seen'],
                'is_favorite': True
            })

        return jsonify({'success': True, 'data': {'favorites': fav_list}, 'error': None})

    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500


@users_bp.route('/favorites/<int:fav_user_id>/toggle', methods=['POST'])
@token_required
def toggle_favorite(current_user, fav_user_id):
    """
    Toggles the favorite status for a target user.
    """
    if current_user['id'] == fav_user_id:
        return jsonify({'success': False, 'data': None, 'error': 'You cannot favorite yourself'}), 400

    try:
        with get_creds_db() as conn:
            # Check if target user exists
            target = conn.execute('SELECT id FROM users WHERE id = ?', (fav_user_id,)).fetchone()
            if not target:
                return jsonify({'success': False, 'data': None, 'error': 'User not found'}), 404

            # Check if already favorited
            fav = conn.execute(
                'SELECT 1 FROM favorites WHERE user_id = ? AND favorite_user_id = ?',
                (current_user['id'], fav_user_id)
            ).fetchone()

            if fav:
                # Remove from favorites
                conn.execute(
                    'DELETE FROM favorites WHERE user_id = ? AND favorite_user_id = ?',
                    (current_user['id'], fav_user_id)
                )
                is_fav = False
            else:
                # Add to favorites
                conn.execute(
                    'INSERT INTO favorites (user_id, favorite_user_id) VALUES (?, ?)',
                    (current_user['id'], fav_user_id)
                )
                is_fav = True

            conn.commit()

        return jsonify({
            'success': True,
            'data': {'favorite_user_id': fav_user_id, 'is_favorite': is_fav},
            'error': None
        })

    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500


# --- DEVELOPER ONLY ENDPOINTS ---
from auth.routes import dev_required
from db.database import get_data_db


@users_bp.route('/<int:target_user_id>', methods=['DELETE'])
@dev_required
def dev_delete_user(current_user, target_user_id):
    """
    [DEV ONLY] Permanently deletes another user account and all their chat/session data.
    """
    if current_user['id'] == target_user_id:
        return jsonify({'success': False, 'data': None, 'error': 'Cannot delete your own account via Dev panel. Use /auth/delete.'}), 400

    try:
        # Delete from DATA_DB
        with get_data_db() as conn:
            conn.execute('DELETE FROM messages WHERE user_id = ?', (target_user_id,))
            conn.execute('DELETE FROM summaries WHERE user_id = ?', (target_user_id,))
            conn.execute('DELETE FROM direct_messages WHERE sender_id = ? OR receiver_id = ?', (target_user_id, target_user_id))
            conn.commit()

        # Delete from CREDS_DB
        with get_creds_db() as conn:
            conn.execute('DELETE FROM sessions WHERE user_id = ?', (target_user_id,))
            conn.execute('DELETE FROM favorites WHERE user_id = ? OR favorite_user_id = ?', (target_user_id, target_user_id))
            res = conn.execute('DELETE FROM users WHERE id = ?', (target_user_id,))
            conn.commit()
            
            if res.rowcount == 0:
                return jsonify({'success': False, 'data': None, 'error': 'User not found'}), 404

        return jsonify({'success': True, 'data': {'message': f'User {target_user_id} deleted successfully by Dev'}, 'error': None})
    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500


@users_bp.route('/<int:target_user_id>/tag', methods=['PATCH'])
@dev_required
def dev_update_user_tag(current_user, target_user_id):
    """
    [DEV ONLY] Updates a user's tag ('dev' or 'user').
    """
    from flask import request
    data = request.get_json()
    if not data or 'tag' not in data:
        return jsonify({'success': False, 'data': None, 'error': 'tag field is required'}), 400

    new_tag = str(data['tag']).strip().lower()
    if new_tag not in ['dev', 'user']:
        return jsonify({'success': False, 'data': None, 'error': 'Invalid tag. Allowed tags: dev, user'}), 400

    try:
        with get_creds_db() as conn:
            res = conn.execute('UPDATE users SET tag = ? WHERE id = ?', (new_tag, target_user_id))
            conn.commit()
            if res.rowcount == 0:
                return jsonify({'success': False, 'data': None, 'error': 'User not found'}), 404

        return jsonify({'success': True, 'data': {'user_id': target_user_id, 'tag': new_tag}, 'error': None})
    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500


@users_bp.route('/<int:target_user_id>/instructions', methods=['PATCH'])
@dev_required
def dev_update_user_instructions(current_user, target_user_id):
    """
    [DEV ONLY] Sets custom system instructions dictating how Yuki must talk to this specific user.
    """
    from flask import request
    data = request.get_json()
    if data is None or 'custom_instructions' not in data:
        return jsonify({'success': False, 'data': None, 'error': 'custom_instructions field is required'}), 400

    instructions = data['custom_instructions']

    try:
        with get_creds_db() as conn:
            res = conn.execute('UPDATE users SET custom_instructions = ? WHERE id = ?', (instructions, target_user_id))
            conn.commit()
            if res.rowcount == 0:
                return jsonify({'success': False, 'data': None, 'error': 'User not found'}), 404

        return jsonify({
            'success': True,
            'data': {
                'user_id': target_user_id,
                'custom_instructions': instructions,
                'message': 'Custom Yuki talk instructions updated for target user'
            },
            'error': None
        })
    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500

