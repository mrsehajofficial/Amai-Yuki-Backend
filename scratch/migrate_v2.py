import sqlite3
import os
import sys

# Add the backend directory to sys.path to import Config
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import Config

def migrate():
    db_path = Config.CREDS_DB
    print(f"Migrating {db_path}...")
    
    conn = sqlite3.connect(db_path)
    try:
        # Add full_name column
        conn.execute('ALTER TABLE users ADD COLUMN full_name TEXT')
        print("Added full_name column to users table.")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e):
            print("full_name column already exists.")
        else:
            print(f"Error adding full_name: {e}")
            
    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == '__main__':
    migrate()
