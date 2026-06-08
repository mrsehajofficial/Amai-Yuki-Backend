import sys
import os
import unittest
from unittest.mock import patch

# Add parent directory to path to find app, db, config etc.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from db.database import get_creds_db, get_data_db

class TestReasoning(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.username = "test_reasoning_user"
        self.email = "test_reasoning@example.com"
        self.password = "password123"
        self.api_key = "sk_mock_cerebras_key"

        # Clean up database first if user exists
        self.clean_up()

        # Register the test user
        register_payload = {
            "username": self.username,
            "email": self.email,
            "password": self.password,
            "primary_key": self.api_key
        }
        res = self.client.post('/auth/register', json=register_payload)
        self.assertEqual(res.status_code, 201)

        # Login to get token
        login_payload = {
            "email": self.email,
            "password": self.password
        }
        res = self.client.post('/auth/login', json=login_payload)
        self.assertEqual(res.status_code, 200)
        self.token = res.get_json()['data']['token']
        self.headers = {
            "Authorization": f"Bearer {self.token}"
        }

    def clean_up(self):
        user_id = None
        with get_creds_db() as conn:
            # Check if table exists (in case init is not fully finished or in a weird state)
            try:
                user = conn.execute("SELECT id FROM users WHERE email = ?", (self.email,)).fetchone()
                if user:
                    user_id = user['id']
                    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
                    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
                    conn.commit()
            except sqlite3.OperationalError:
                pass

        if user_id:
            with get_data_db() as conn:
                try:
                    conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
                    conn.commit()
                except sqlite3.OperationalError:
                    pass

    def tearDown(self):
        self.clean_up()

    @patch('requests.post')
    def test_reasoning_flow(self, mock_post):
        # Setup mock API response
        mock_response = mock_post.return_value
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-30b3c3d8-ca41-48e7-9ef0-27e322604a13",
            "choices": [
                {
                    "finish_reason": "stop",
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello! 👋 How can I help you today?",
                        "reasoning": "The user just says \"Hello!\" with no further context.\n\nWe need to respond politely.",
                        "tool_calls": None
                    }
                }
            ],
            "created": 1769729480,
            "model": "zai-glm-4.7",
            "usage": {
                "total_tokens": 128
            }
        }

        # Call send message endpoint with extra reasoning params
        send_payload = {
            "message": "Hello!",
            "model": "chat",  # Resolves to zai-glm-4.7
            "reasoning_effort": "none",
            "clear_thinking": False
        }
        
        response = self.client.post('/chat/send', json=send_payload, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        
        res_json = response.get_json()
        self.assertTrue(res_json['success'])
        self.assertEqual(res_json['data']['reply'], "Hello! 👋 How can I help you today?")
        self.assertEqual(res_json['data']['reasoning'], "The user just says \"Hello!\" with no further context.\n\nWe need to respond politely.")
        self.assertEqual(res_json['data']['model_used'], "zai-glm-4.7")

        # Verify that mock_post was called with the correct parameters
        self.assertTrue(mock_post.called)
        call_args, call_kwargs = mock_post.call_args
        request_body = call_kwargs['json']
        
        self.assertEqual(request_body['model'], "zai-glm-4.7")
        self.assertEqual(request_body['reasoning_effort'], "none")
        self.assertEqual(request_body['clear_thinking'], False)

        # Call history endpoint to verify saving and loading reasoning
        history_response = self.client.get('/chat/history', headers=self.headers)
        self.assertEqual(history_response.status_code, 200)
        history_json = history_response.get_json()
        self.assertTrue(history_json['success'])
        
        messages = history_json['data']['messages']
        # The history returns newest first, so the assistant message is index 0
        assistant_msg = messages[0]
        self.assertEqual(assistant_msg['role'], 'assistant')
        self.assertEqual(assistant_msg['content'], "Hello! 👋 How can I help you today?")
        self.assertEqual(assistant_msg['reasoning'], "The user just says \"Hello!\" with no further context.\n\nWe need to respond politely.")

        # The user message is index 1, and it should not have reasoning (should be None/null)
        user_msg = messages[1]
        self.assertEqual(user_msg['role'], 'user')
        self.assertEqual(user_msg['content'], "Hello!")
        self.assertIsNone(user_msg['reasoning'])

        print("SUCCESS: Reasoning integration tests passed successfully!")

if __name__ == '__main__':
    unittest.main()
