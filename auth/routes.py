import sqlite3
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
from datetime import datetime, timedelta
from functools import wraps
from db.database import get_creds_db
from config import Config

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')
        
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            
        if not token:
            return jsonify({'success': False, 'data': None, 'error': 'Token is missing!'}), 401

        try:
            with get_creds_db() as conn:
                session = conn.execute(
                    'SELECT user_id, expires_at FROM sessions WHERE token = ?', 
                    (token,)
                ).fetchone()

                if not session:
                    return jsonify({'success': False, 'data': None, 'error': 'Invalid token!'}), 401
                
                expires_at_str = session['expires_at']
                try:
                    expires_at = datetime.strptime(expires_at_str, '%Y-%m-%d %H:%M:%S.%f')
                except ValueError:
                    try:
                        expires_at = datetime.strptime(expires_at_str, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        expires_at = datetime.min

                if expires_at < datetime.utcnow():
                    # Delete expired session
                    conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
                    conn.commit()
                    return jsonify({'success': False, 'data': None, 'error': 'Token has expired!'}), 401
                
                user = conn.execute(
                    'SELECT id, username, full_name, email, primary_key, fallback_key, nsfw_mode, model, profile_pic, yuki_impression, last_seen FROM users WHERE id = ?',
                    (session['user_id'],)
                ).fetchone()
                
                if not user:
                    return jsonify({'success': False, 'data': None, 'error': 'User not found!'}), 401
                
                # Update last_seen timestamp
                conn.execute('UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE id = ?', (user['id'],))
                conn.commit()

                # Inject user dict into kwargs or request context
                # For simplicity, we'll pass it as a kwarg named current_user
                kwargs['current_user'] = dict(user)
                
        except Exception as e:
            print(f"Auth Decorator Error: {e}")
            return jsonify({'success': False, 'data': None, 'error': str(e)}), 500

        return f(*args, **kwargs)
    return decorated

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    
    if not data or not data.get('username') or not data.get('email') or not data.get('password') or not data.get('primary_key'):
        return jsonify({'success': False, 'data': None, 'error': 'Missing required fields'}), 400

    hashed_password = generate_password_hash(data['password'])
    
    try:
        with get_creds_db() as conn:
            # Check for case-insensitive duplicate username
            existing_user = conn.execute(
                'SELECT id FROM users WHERE username = ? COLLATE NOCASE',
                (data['username'],)
            ).fetchone()
            
            if existing_user:
                return jsonify({'success': False, 'data': None, 'error': 'Username already exists'}), 409
            
            # Check for duplicate email
            existing_email = conn.execute(
                'SELECT id FROM users WHERE email = ?',
                (data['email'],)
            ).fetchone()
            
            if existing_email:
                return jsonify({'success': False, 'data': None, 'error': 'Email already registered'}), 409

            conn.execute('''
                INSERT INTO users (username, email, password_hash, primary_key, fallback_key)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                data['username'], 
                data['email'], 
                hashed_password, 
                data['primary_key'], 
                data.get('fallback_key')
            ))
            conn.commit()
            
        return jsonify({'success': True, 'data': {'message': 'User created successfully'}, 'error': None}), 201
        
    except sqlite3.IntegrityError as e:
        print(f"Registration IntegrityError: {e}")
        return jsonify({'success': False, 'data': None, 'error': 'Username or email already exists'}), 409
    except Exception as e:
        print(f"Registration General Error: {e}")
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'success': False, 'data': None, 'error': 'Could not verify'}), 401

    with get_creds_db() as conn:
        user = conn.execute('SELECT id, password_hash FROM users WHERE email = ?', (data['email'],)).fetchone()

        if not user or not check_password_hash(user['password_hash'], data['password']):
            return jsonify({'success': False, 'data': None, 'error': 'Invalid email or password'}), 401

        token = secrets.token_hex(32)
        expires_at = datetime.utcnow() + timedelta(days=Config.SESSION_EXPIRY_DAYS)
        
        conn.execute('''
            INSERT INTO sessions (user_id, token, expires_at)
            VALUES (?, ?, ?)
        ''', (user['id'], token, expires_at.strftime('%Y-%m-%d %H:%M:%S.%f')))
        conn.commit()

        return jsonify({
            'success': True, 
            'data': {
                'token': token,
                'expires_at': expires_at.isoformat()
            }, 
            'error': None
        })

@auth_bp.route('/logout', methods=['POST'])
@token_required
def logout(current_user):
    auth_header = request.headers.get('Authorization')
    token = auth_header.split(' ')[1]
    
    with get_creds_db() as conn:
        conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
        conn.commit()
        
    return jsonify({'success': True, 'data': {'message': 'Logged out successfully'}, 'error': None})

@auth_bp.route('/me', methods=['GET'])
@token_required
def get_me(current_user):
    # Hide sensitive API keys in the response
    user_data = current_user.copy()
    user_data['primary_key'] = '***' + user_data['primary_key'][-4:] if user_data['primary_key'] else None
    if user_data['fallback_key']:
        user_data['fallback_key'] = '***' + user_data['fallback_key'][-4:]
        
    return jsonify({'success': True, 'data': user_data, 'error': None})

@auth_bp.route('/settings', methods=['PATCH'])
@token_required
def update_settings(current_user):
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'data': None, 'error': 'No data provided'}), 400
        
    updates = []
    params = []
    
    if 'nsfw_mode' in data:
        updates.append('nsfw_mode = ?')
        params.append(1 if data['nsfw_mode'] else 0)
        
    if 'model' in data:
        # We need to be careful when saving settings. If the client sends a Map,
        # a key, or a stringified map representation, we resolve it to the full, 
        # clean model name before saving it to the SQLite database.
        resolved_model = Config.resolve_model(data['model'])
        if resolved_model:
            updates.append('model = ?')
            params.append(resolved_model)
        else:
            return jsonify({'success': False, 'data': None, 'error': 'Invalid model selection'}), 400
            
    if 'fallback_key' in data:
        updates.append('fallback_key = ?')
        params.append(data['fallback_key'])

    if 'full_name' in data:
        updates.append('full_name = ?')
        params.append(data['full_name'])

    if 'profile_pic' in data:
        updates.append('profile_pic = ?')
        params.append(data['profile_pic'])

    if not updates:
        return jsonify({'success': False, 'data': None, 'error': 'No valid fields to update'}), 400

    params.append(current_user['id'])
    query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
    
    with get_creds_db() as conn:
        conn.execute(query, tuple(params))
        conn.commit()
        
    return jsonify({'success': True, 'data': {'message': 'Profile updated successfully'}, 'error': None})

@auth_bp.route('/nsfw/toggle', methods=['POST'])
@token_required
def toggle_nsfw(current_user):
    """
    Dedicated endpoint to toggle NSFW mode on/off.
    """
    new_mode = 0 if current_user.get('nsfw_mode', 0) else 1
    
    try:
        with get_creds_db() as conn:
            conn.execute('UPDATE users SET nsfw_mode = ? WHERE id = ?', (new_mode, current_user['id']))
            conn.commit()
            
        return jsonify({
            'success': True, 
            'data': {
                'nsfw_mode': bool(new_mode),
                'message': f"NSFW mode {'enabled' if new_mode else 'disabled'}"
            }, 
            'error': None
        })
    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500

@auth_bp.route('/heartbeat', methods=['POST'])
@token_required
def heartbeat(current_user):
    """
    Simple ping to keep the user's online status active.
    last_seen is updated automatically by @token_required.
    """
    return jsonify({'success': True, 'data': {'status': 'active'}, 'error': None})

@auth_bp.route('/delete', methods=['DELETE'])
@token_required
def delete_account(current_user):
    """
    Permanently deletes the user account and all associated data.
    This includes credentials, sessions, AI chat history, and direct messages.
    """
    user_id = current_user['id']
    
    try:
        # 1. Delete data from DATA_DB (AI chat, summaries, direct messages)
        from db.database import get_data_db
        with get_data_db() as conn:
            # Delete AI messages and summaries
            conn.execute('DELETE FROM messages WHERE user_id = ?', (user_id,))
            conn.execute('DELETE FROM summaries WHERE user_id = ?', (user_id,))
            # Delete direct messages (both as sender and receiver)
            conn.execute('DELETE FROM direct_messages WHERE sender_id = ? OR receiver_id = ?', (user_id, user_id))
            conn.commit()

        # 2. Delete data from CREDS_DB (Sessions and User record)
        with get_creds_db() as conn:
            # Delete all sessions for this user
            conn.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))
            # Delete the user record
            conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
            conn.commit()

        return jsonify({'success': True, 'data': {'message': 'Account deleted successfully'}, 'error': None})

    except Exception as e:
        return jsonify({'success': False, 'data': None, 'error': str(e)}), 500
