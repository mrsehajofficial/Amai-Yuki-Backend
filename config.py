import os
import tempfile

class Config:
    # App Settings
    SECRET_KEY = os.environ.get('SECRET_KEY', 'ama1-yuk1-sup3r-s3cr3t-k3y-2026')
    SESSION_EXPIRY_DAYS = 7
    
    # DB Paths
    DB_DIR = os.environ.get('DB_DIR', tempfile.gettempdir())
    CREDS_DB = os.path.join(DB_DIR, 'creds.db')
    DATA_DB = os.path.join(DB_DIR, 'data.db')
    
    # --- Provider Settings ---
    DEFAULT_PROVIDER = os.environ.get('AI_PROVIDER', 'cerebras')

    # --- ByNara Cloud AI Settings ---
    # Primary: direct call to ByNara (fast, no middleman)
    AI_BASE_URL = os.environ.get('AI_BASE_URL', "https://router.bynara.id/v1/chat/completions")
    
    # Fallback: Google Apps Script proxy (slow but reliable — used only if direct call fails)
    AI_PROXY_URL = os.environ.get(
        'AI_PROXY_URL',
        'https://script.google.com/macros/s/AKfycbyhEax-8NBsVMv5e4g6hwsOqms-NWNiWfOINqrS8GGc8vFwJGB-18xuuuqRMcEZkQs8/exec'
    )

    AI_REQUEST_TIMEOUT = int(os.environ.get('AI_REQUEST_TIMEOUT', '60'))
    
    MODELS = {
        "omni": "agnes-2.0-flash",
        "chat": "mistral-medium-3-5"
    }
    
    DEFAULT_MODEL = MODELS["chat"]

    # --- Ollama Local AI Settings ---
    OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')
    
    OLLAMA_MODELS = {
        "chat": "tinydolphin",
        "omni": "dolphin-phi"
    }
    
    OLLAMA_DEFAULT_MODEL = OLLAMA_MODELS["omni"]
    
    OLLAMA_NUM_CTX = int(os.environ.get('OLLAMA_NUM_CTX', '2048'))
    
    # Context settings
    MAX_HISTORY_MESSAGES = 4
    MESSAGES_BEFORE_SUMMARY = 10

    @classmethod
    def resolve_model(cls, model_raw):
        if not model_raw:
            return None
        
        if isinstance(model_raw, dict):
            val = model_raw.get('value') or model_raw.get('key')
            if val:
                return cls.resolve_model(val)
        
        if isinstance(model_raw, str):
            model_raw = model_raw.strip()
            
            if model_raw.startswith('{') and model_raw.endswith('}'):
                import re
                match = re.search(r'value:\s*([^,\}]+)', model_raw)
                if match:
                    val = match.group(1).strip().strip('\'"')
                    return cls.resolve_model(val)
                match = re.search(r'key:\s*([^,\}]+)', model_raw)
                if match:
                    key = match.group(1).strip().strip('\'"')
                    return cls.resolve_model(key)
            
            if model_raw in cls.MODELS.values():
                return model_raw
            if model_raw in cls.MODELS:
                return cls.MODELS[model_raw]
            if model_raw in cls.OLLAMA_MODELS.values():
                return model_raw
            if model_raw in cls.OLLAMA_MODELS:
                return cls.OLLAMA_MODELS[model_raw]
                
        return None

    @classmethod
    def resolve_ollama_model(cls, model_raw):
        if not model_raw:
            return cls.OLLAMA_DEFAULT_MODEL
        
        if isinstance(model_raw, str):
            model_raw = model_raw.strip()
            if model_raw in cls.OLLAMA_MODELS.values():
                return model_raw
            if model_raw in cls.OLLAMA_MODELS:
                return cls.OLLAMA_MODELS[model_raw]
            for key, cerebras_model in cls.MODELS.items():
                if model_raw == cerebras_model or model_raw == key:
                    return cls.OLLAMA_MODELS.get(key, cls.OLLAMA_DEFAULT_MODEL)
            return model_raw
        
        return cls.OLLAMA_DEFAULT_MODEL

    @classmethod
    def resolve_provider(cls, provider_raw):
        if not provider_raw:
            return cls.DEFAULT_PROVIDER
        if isinstance(provider_raw, str):
            provider_raw = provider_raw.strip().lower()
            if provider_raw in ('cerebras', 'ollama'):
                return provider_raw
        return cls.DEFAULT_PROVIDER

    @classmethod
    def get_models_for_provider(cls, provider=None):
        if not provider:
            provider = cls.DEFAULT_PROVIDER
        if provider == 'ollama':
            return cls.OLLAMA_MODELS, cls.OLLAMA_DEFAULT_MODEL
        else:
            return cls.MODELS, cls.DEFAULT_MODEL
