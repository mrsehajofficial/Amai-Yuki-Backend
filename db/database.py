import sqlite3
import os
from config import Config

def get_creds_db():
    conn = sqlite3.connect(Config.CREDS_DB)
    conn.row_factory = sqlite3.Row
    return conn

def get_data_db():
    conn = sqlite3.connect(Config.DATA_DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(Config.DB_DIR, exist_ok=True)
    
    # Initialize Credentials DB
    # Note: SQLite does not support ? placeholders in DDL statements,
    # so we use an f-string to safely inject the default model at startup time.
    with get_creds_db() as conn:
        conn.execute(f'''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE COLLATE NOCASE NOT NULL,
                full_name TEXT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                primary_key TEXT NOT NULL,
                fallback_key TEXT,
                nsfw_mode INTEGER DEFAULT 0,
                model TEXT DEFAULT '{Config.DEFAULT_MODEL}',
                profile_pic TEXT,
                yuki_impression TEXT,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS favorites (
                user_id INTEGER NOT NULL,
                favorite_user_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, favorite_user_id),
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (favorite_user_id) REFERENCES users (id)
            )
        ''')
        
    # Initialize Data DB
    with get_data_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_pinned INTEGER DEFAULT 0
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                summary_text TEXT NOT NULL,
                message_count INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS direct_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                reaction TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sender_id) REFERENCES users (id),
                FOREIGN KEY (receiver_id) REFERENCES users (id)
            )
        ''')

        # Cache/Summary of direct peer-to-peer chat logs.
        # This keeps a high-density consolidated digest of the user's relations and plans
        # so Yuki can pull it in sub-milliseconds without performing expensive database scans
        # or runtime LLM calls during regular chat cycles.
        conn.execute('''
            CREATE TABLE IF NOT EXISTS direct_chat_summaries (
                user_id INTEGER PRIMARY KEY,
                summary_text TEXT NOT NULL,
                message_count INTEGER NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

    # Self-healing database migration for adding reaction column to existing installations
    with get_data_db() as conn:
        try:
            conn.execute("ALTER TABLE direct_messages ADD COLUMN reaction TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            # Column already exists, perfectly safe to ignore
            pass
            
    # Self-healing database migration for adding is_pinned column to messages table
    with get_data_db() as conn:
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN is_pinned INTEGER DEFAULT 0")
            conn.commit()
        except sqlite3.OperationalError:
            # Column already exists, perfectly safe to ignore
            pass

    # Self-healing database migration for adding yuki_impression column to users table
    with get_creds_db() as conn:
        try:
            conn.execute("ALTER TABLE users ADD COLUMN yuki_impression TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            # Column already exists, perfectly safe to ignore
            pass

# Run init on module load
init_db()
