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

    @classmethod
    def resolve_model(cls, model_raw):
        """
        Hey there! This is a little helper to deal with the chaos of frontend serialization.
        Sometimes the Flutter client sends the model as a clean string key, sometimes it's the 
        full name, sometimes it's a Map, and sometimes (thanks to Dart's default serialization)
        it literally comes in as a string representation of a Map: "{key: chat, value: ...}".
        
        This method gently unpacks all of that so we always end up with a valid model name
        that our API endpoints actually understand. If we absolutely can't make sense of it,
        we return None so the caller can fallback or handle the validation error.
        """
        if not model_raw:
            return None
        
        # If it's a dictionary/map, extract the value or key and try again recursively
        if isinstance(model_raw, dict):
            val = model_raw.get('value') or model_raw.get('key')
            if val:
                return cls.resolve_model(val)
        
        # If it's a string, we need to inspect it closely
        if isinstance(model_raw, str):
            model_raw = model_raw.strip()
            
            # Check for Dart's Map.toString() output: "{key: chat, value: LongCat-Flash-Chat-2602-Exp}"
            if model_raw.startswith('{') and model_raw.endswith('}'):
                import re
                
                # Look for a 'value:' pair in the stringified map
                match = re.search(r'value:\s*([^,\}]+)', model_raw)
                if match:
                    # Strip any potential quotes or whitespace
                    val = match.group(1).strip().strip('\'"')
                    return cls.resolve_model(val)
                    
                # If no value was specified, check for a 'key:' pair
                match = re.search(r'key:\s*([^,\}]+)', model_raw)
                if match:
                    key = match.group(1).strip().strip('\'"')
                    return cls.resolve_model(key)
            
            # If it matches one of our actual model values, we're golden!
            if model_raw in cls.MODELS.values():
                return model_raw
                
            # If it's a key from our MODELS dictionary, map it to the full name
            if model_raw in cls.MODELS:
                return cls.MODELS[model_raw]
                
        return None
