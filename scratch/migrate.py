import sqlite3
import os

# Path to the credentials database
db_path = r'x:\Yuki Backend\db\creds.db'

def migrate():
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if last_seen exists
        cursor.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'last_seen' not in columns:
            print("Adding 'last_seen' column to 'users' table...")
            # SQLite ALTER TABLE requires a constant default. We'll use a fixed timestamp 
            # and then update existing rows if needed.
            cursor.execute("ALTER TABLE users ADD COLUMN last_seen TIMESTAMP DEFAULT '2026-01-01 00:00:00'")
            cursor.execute("UPDATE users SET last_seen = CURRENT_TIMESTAMP")
            conn.commit()
            print("Column added and initialized successfully.")
        else:
            print("'last_seen' column already exists.")

        if 'profile_pic' not in columns:
            print("Adding 'profile_pic' column to 'users' table...")
            cursor.execute("ALTER TABLE users ADD COLUMN profile_pic TEXT")
            conn.commit()
            print("Profile pic column added successfully.")

        if 'full_name' not in columns:
            print("Adding 'full_name' column to 'users' table...")
            cursor.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
            conn.commit()
            print("Full name column added successfully.")

    except Exception as e:
        print(f"Error during migration: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
