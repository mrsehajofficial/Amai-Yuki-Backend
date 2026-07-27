import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import create_app
from db.database import get_creds_db

def test():
    app = create_app()
    client = app.test_client()
    
    # Let's insert a test user or fetch one
    with get_creds_db() as conn:
        # Check if user exists
        user = conn.execute("SELECT id, primary_key, fallback_key FROM users LIMIT 1").fetchone()
        if not user:
            print("No users in DB. Registering one...")
            res = client.post('/auth/register', json={
                "username": "testbug",
                "email": "testbug@example.com",
                "password": "password123",
                "primary_key": "original_primary",
                "fallback_key": "original_fallback"
            })
            print("Register status:", res.status_code)
            user = conn.execute("SELECT id, primary_key, fallback_key FROM users LIMIT 1").fetchone()
            
        user_id = user['id']
        print(f"Test user id: {user_id}")
        
    # Login
    res = client.post('/auth/login', json={
        "email": "testbug@example.com" if not user else conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()['email'],
        "password": "password123"
    })
    print("Login status:", res.status_code)
    token = res.get_json()['data']['token']
    headers = {"Authorization": f"Bearer {token}"}
    
    # Get Me to see the masked fallback key
    me_res = client.get('/auth/me', headers=headers)
    print("Me response:", me_res.get_json())
    
    # Call settings with primary_key but without fallback_key (or fallback_key = null)
    # This simulates frontend sending only primary_key
    patch_res = client.patch('/auth/settings', json={
        "primary_key": "new_primary_key"
    }, headers=headers)
    print("Patch with only primary_key status:", patch_res.status_code)
    print("Patch response:", patch_res.get_json())
    
    # What if frontend sends fallback_key as ***xxxx ?
    patch_res2 = client.patch('/auth/settings', json={
        "primary_key": "another_primary_key",
        "fallback_key": "***lback"
    }, headers=headers)
    print("Patch with fallback_key=***lback status:", patch_res2.status_code)
    print("Patch response:", patch_res2.get_json())

if __name__ == "__main__":
    test()
