import sys
import os
import unittest
from unittest.mock import patch

# Add parent directory to path to find app, db, config etc.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from db.database import get_creds_db, get_data_db
from config import Config

class TestOllamaIntegration(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.username = "test_ollama_user"
        self.email = "test_ollama@example.com"
        self.password = "password123"

        self.clean_up()

    def clean_up(self):
        user_id = None
        with get_creds_db() as conn:
            try:
                user = conn.execute("SELECT id FROM users WHERE email = ?", (self.email,)).fetchone()
                if user:
                    user_id = user['id']
                    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
                    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
                    conn.commit()
            except Exception:
                pass

        if user_id:
            with get_data_db() as conn:
                try:
                    conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
                    conn.execute("DELETE FROM summaries WHERE user_id = ?", (user_id,))
                    conn.execute("DELETE FROM direct_chat_summaries WHERE user_id = ?", (user_id,))
                    conn.commit()
                except Exception:
                    pass

    def tearDown(self):
        self.clean_up()

    @patch('requests.post')
    def test_ollama_flow(self, mock_post):
        # 1. Register with Ollama provider (should not require primary_key)
        register_payload = {
            "username": self.username,
            "email": self.email,
            "password": self.password,
            "provider": "ollama"
        }
        res = self.client.post('/auth/register', json=register_payload)
        self.assertEqual(res.status_code, 201)

        # 2. Login to get token
        login_payload = {
            "email": self.email,
            "password": self.password
        }
        res = self.client.post('/auth/login', json=login_payload)
        self.assertEqual(res.status_code, 200)
        token = res.get_json()['data']['token']
        headers = {
            "Authorization": f"Bearer {token}"
        }

        # 3. Verify '/auth/me' returns provider = 'ollama' and placeholder key
        me_res = self.client.get('/auth/me', headers=headers)
        self.assertEqual(me_res.status_code, 200)
        me_json = me_res.get_json()
        self.assertEqual(me_json['data']['provider'], 'ollama')
        self.assertIn('ocal', me_json['data']['primary_key'])

        # 4. Mock the local Ollama API
        mock_response = mock_post.return_value
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "model": "tinydolphin",
            "message": {
                "role": "assistant",
                "content": "Amai Yuki here! What's up, baby? 💦"
            },
            "eval_count": 12,
            "prompt_eval_count": 45
        }

        # 5. Send message with model override or default (resolves to tinydolphin)
        send_payload = {
            "message": "Hi Yuki!"
        }
        chat_res = self.client.post('/chat/send', json=send_payload, headers=headers)
        self.assertEqual(chat_res.status_code, 200)
        chat_json = chat_res.get_json()
        self.assertTrue(chat_json['success'])
        self.assertEqual(chat_json['data']['reply'], "Amai Yuki here! What's up, baby? 💦")
        self.assertEqual(chat_json['data']['model_used'], "tinydolphin")

        # Verify Ollama URL was called
        self.assertTrue(mock_post.called)
        called_url = mock_post.call_args[0][0]
        self.assertEqual(called_url, f"{Config.OLLAMA_BASE_URL}/api/chat")

        # 6. Verify listing models for Ollama provider
        models_res = self.client.get('/chat/models', headers=headers)
        self.assertEqual(models_res.status_code, 200)
        models_json = models_res.get_json()
        self.assertEqual(models_json['data']['provider'], 'ollama')
        models_keys = [item['key'] for item in models_json['data']['models']]
        self.assertIn('chat', models_keys)
        self.assertIn('omni', models_keys)

        print("SUCCESS: Ollama registration, dispatch, and chat tests passed!")

if __name__ == '__main__':
    unittest.main()
