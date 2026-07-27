import sys
import os
import requests

# Add parent directory to path to find config
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import Config

def test_local_ollama():
    print(f"Connecting to Ollama at {Config.OLLAMA_BASE_URL}...")
    try:
        # Check if Ollama is running
        res = requests.get(Config.OLLAMA_BASE_URL)
        if res.status_code == 200:
            print("[OK] Ollama is running!")
    except Exception as e:
        print(f"[FAIL] Failed to connect to Ollama. Make sure the app is running in the system tray. Error: {e}")
        return

    # Check tags / pulled models
    try:
        tags_res = requests.get(f"{Config.OLLAMA_BASE_URL}/api/tags")
        if tags_res.status_code == 200:
            models_list = [m['name'] for m in tags_res.json().get('models', [])]
            print(f"Pulled models found: {models_list}")
            
            chat_model = Config.OLLAMA_DEFAULT_MODEL
            # Check for version suffixes (e.g. "tinydolphin:latest")
            has_chat_model = any(chat_model in m for m in models_list)
            
            if has_chat_model:
                print(f"[OK] Required model '{chat_model}' is pulled and ready!")
            else:
                print(f"[WARN] Model '{chat_model}' might not be pulled or named differently. Standard names: {models_list}")
    except Exception as e:
        print(f"[FAIL] Error checking models list: {e}")

    # Try a chat completion
    print("\nSending a test prompt to Ollama...")
    payload = {
        "model": Config.OLLAMA_DEFAULT_MODEL,
        "messages": [
            {"role": "user", "content": "Say 'Amai Yuki is ready!'"}
        ],
        "stream": False
    }
    try:
        chat_res = requests.post(f"{Config.OLLAMA_BASE_URL}/api/chat", json=payload, timeout=30)
        if chat_res.status_code == 200:
            reply = chat_res.json().get('message', {}).get('content', '')
            print(f"Response from Ollama: {reply}")
            print("\n[SUCCESS] The local Ollama server is communicating correctly and responding!")
        else:
            print(f"[FAIL] Ollama returned status code {chat_res.status_code}: {chat_res.text}")
    except Exception as e:
        print(f"[FAIL] Chat request failed: {e}")

if __name__ == "__main__":
    test_local_ollama()
