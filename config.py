import os

class Config:
    # App Settings
    SECRET_KEY = os.environ.get('SECRET_KEY', 'ama1-yuk1-sup3r-s3cr3t-k3y-2026')
    SESSION_EXPIRY_DAYS = 7
    
    # DB Paths
    DB_DIR = os.path.join(os.path.dirname(__file__), 'db')
    CREDS_DB = os.path.join(DB_DIR, 'creds.db')
    DATA_DB = os.path.join(DB_DIR, 'data.db')
    
    # --- Provider Settings ---
    # Set AI_PROVIDER env var to 'ollama' to use local Ollama, or 'cerebras' for cloud.
    # Both can run simultaneously — each user can have their own provider preference.
    DEFAULT_PROVIDER = os.environ.get('AI_PROVIDER', 'cerebras')

    # --- ByNara Cloud AI Settings (routed via Google Apps Script proxy) ---
    # Upstream ByNara endpoint. The backend no longer calls it directly —
    # requests go through the static Apps Script proxy below, which relays
    # to this URL. Kept here for reference/debugging.
    AI_BASE_URL = "https://router.bynara.id/v1/chat/completions"

    # Architecture:
    #   PythonAnywhere (this backend)
    #       │  API key + request (key used once, never stored)
    #       ▼
    #   Google Apps Script proxy  (holds NO keys, just forwards)
    #       │  same payload + "Authorization: Bearer <key>"
    #       ▼
    #   ByNara router
    #
    # The ByNara key NEVER lives in Apps Script. It stays here on PythonAnywhere
    # in each user's creds.db record (primary_key / fallback_key) and is only
    # ever forwarded once per request — never persisted on Google's side.
    AI_PROXY_URL = os.environ.get(
        'AI_PROXY_URL',
        'https://script.google.com/macros/s/AKfycbyhEax-8NBsVMv5e4g6hwsOqms-NWNiWfOINqrS8GGc8vFwJGB-18xuuuqRMcEZkQs8/exec'
    )

    # Apps Script web apps can cold-start slowly and LLM calls take time.
    AI_REQUEST_TIMEOUT = int(os.environ.get('AI_REQUEST_TIMEOUT', '90'))
    
    MODELS = {
        "omni": "agnes-2.0-flash",
        "chat": "mistral-medium-3-5"
    }
    
    DEFAULT_MODEL = MODELS["chat"]

    # --- Ollama Local AI Settings ---
    # Ollama runs locally — no API keys, no cloud bills, no censorship. Pure freedom.
    # These models are specifically chosen for low-end hardware (4GB RAM, integrated GPUs).
    OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')
    
    # Ultra-lightweight uncensored models from the dolphin family.
    # tinydolphin: 1.1B params (~670MB) — runs on literally any PC with 4GB RAM
    # dolphin-phi: 2.7B params (~1.6GB) — slightly better quality, still light as fuck
    OLLAMA_MODELS = {
        "chat": "tinydolphin",
        "omni": "dolphin-phi"
    }
    
    OLLAMA_DEFAULT_MODEL = OLLAMA_MODELS["omni"]
    
    # Context window for Ollama — keep it conservative for potato PCs.
    # 2048 is safe for 4GB RAM. Bump to 4096 or 8192 if you have more juice.
    OLLAMA_NUM_CTX = int(os.environ.get('OLLAMA_NUM_CTX', '2048'))
    
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
            
            # If it matches one of our actual model values (Cerebras), we're golden!
            if model_raw in cls.MODELS.values():
                return model_raw
                
            # If it's a key from our MODELS dictionary, map it to the full name
            if model_raw in cls.MODELS:
                return cls.MODELS[model_raw]

            # Also check Ollama models
            if model_raw in cls.OLLAMA_MODELS.values():
                return model_raw
            
            if model_raw in cls.OLLAMA_MODELS:
                return cls.OLLAMA_MODELS[model_raw]
                
        return None

    @classmethod
    def resolve_ollama_model(cls, model_raw):
        """
        Resolves a model name for Ollama specifically.
        If the given model is a Cerebras model name, maps it to the equivalent Ollama model.
        If it's already a valid Ollama model name, returns it directly.
        If we can't figure it out, returns the default Ollama model.
        """
        if not model_raw:
            return cls.OLLAMA_DEFAULT_MODEL
        
        if isinstance(model_raw, str):
            model_raw = model_raw.strip()
            
            # Direct Ollama model name (user specified exactly what they want)
            if model_raw in cls.OLLAMA_MODELS.values():
                return model_raw
            
            # Ollama model key (e.g., "chat" → "tinydolphin")
            if model_raw in cls.OLLAMA_MODELS:
                return cls.OLLAMA_MODELS[model_raw]
            
            # If it's a Cerebras model, map to the equivalent Ollama tier
            for key, cerebras_model in cls.MODELS.items():
                if model_raw == cerebras_model or model_raw == key:
                    return cls.OLLAMA_MODELS.get(key, cls.OLLAMA_DEFAULT_MODEL)
            
            # If it looks like a custom Ollama model name (user pulled something specific),
            # just pass it through — Ollama will handle model-not-found errors
            return model_raw
        
        return cls.OLLAMA_DEFAULT_MODEL

    @classmethod
    def resolve_provider(cls, provider_raw):
        """
        Resolves the provider string. Returns 'cerebras' or 'ollama'.
        Falls back to DEFAULT_PROVIDER if invalid.
        """
        if not provider_raw:
            return cls.DEFAULT_PROVIDER
        
        if isinstance(provider_raw, str):
            provider_raw = provider_raw.strip().lower()
            if provider_raw in ('cerebras', 'ollama'):
                return provider_raw
        
        return cls.DEFAULT_PROVIDER

    @classmethod
    def get_models_for_provider(cls, provider=None):
        """
        Returns the models dict for the given provider.
        Useful for the /models endpoint to show the right model list.
        """
        if not provider:
            provider = cls.DEFAULT_PROVIDER
        
        if provider == 'ollama':
            return cls.OLLAMA_MODELS, cls.OLLAMA_DEFAULT_MODEL
        else:
            return cls.MODELS, cls.DEFAULT_MODEL

