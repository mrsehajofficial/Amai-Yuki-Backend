import os

class Config:
    # App Settings
    SECRET_KEY = os.environ.get('SECRET_KEY', 'ama1-yuk1-sup3r-s3cr3t-k3y-2026')
    SESSION_EXPIRY_DAYS = 7
    
    # DB Paths
    DB_DIR = os.path.join(os.path.dirname(__file__), 'db')
    CREDS_DB = os.path.join(DB_DIR, 'creds.db')
    DATA_DB = os.path.join(DB_DIR, 'data.db')
    
    # AI Settings
    AI_BASE_URL = "https://api.longcat.chat/openai/v1/chat/completions"
    
    MODELS = {
        "omni": "LongCat-Flash-Omni-2603",
        "chat": "LongCat-Flash-Chat-2602-Exp",
        "preview": "LongCat-2.0-Preview"
    }
    
    DEFAULT_MODEL = MODELS["chat"]
    
    # Context settings
    MAX_HISTORY_MESSAGES = 4 # Last 4 messages included
    MESSAGES_BEFORE_SUMMARY = 10 # Trigger summary every 10 messages
