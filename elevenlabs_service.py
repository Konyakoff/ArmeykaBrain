import os
import aiohttp
import uuid

# Кэш для голосов, чтобы не запрашивать их каждый раз
_voices_cache = []

async def get_elevenlabs_voices() -> list:
    global _voices_cache
    if _voices_cache:
        return _voices_cache
        
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        return []
        
    url = "https://api.elevenlabs.io/v1/voices"
    headers = {
        "Accept": "application/json",
        "xi-api-key": api_key
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    voices = data.get("voices", [])
                    extracted = []
                    for v in voices:
                        labels = v.get("labels", {})
                        gender = labels.get("gender", "unknown")
                        age = labels.get("age", "")
                        descriptive = labels.get("descriptive", "")
                        use_case = labels.get("use_case", "")
                        
                        desc_parts = [p for p in [gender, age, descriptive, use_case] if p]
                        desc_str = ", ".join(desc_parts)
                        
                        extracted.append({
                            "voice_id": v.get("voice_id"),
                            "name": v.get("name"),
                            "description": desc_str
                        })
                    _voices_cache = extracted
                    return _voices_cache
    except Exception as e:
        print(f"Error fetching voices: {e}")
    return []

async def generate_audio(text: str, model_id: str, voice_id: str = "pFZP5JQG7iQjIQuC4Bku", speed: float = 1.0, stability: float = 0.5, similarity_boost: float = 0.75) -> str:
    """
    Генерирует аудио из текста с помощью ElevenLabs API и сохраняет в файл.
    Возвращает относительный URL к сохраненному файлу.
    """
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY не установлен в .env")
        
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key
    }
    
    data = {
        "text": text,
        "model_id": model_id,
        "speed": speed,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost
        }
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=headers) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Ошибка ElevenLabs API ({response.status}): {error_text}")
                
            audio_content = await response.read()
            
    # Создаем папку для аудио, если её нет
    audio_dir = os.path.join("static", "audio")
    os.makedirs(audio_dir, exist_ok=True)
    
    # Сохраняем файл
    filename = f"audio_{uuid.uuid4().hex[:8]}.mp3"
    filepath = os.path.join(audio_dir, filename)
    
    with open(filepath, "wb") as f:
        f.write(audio_content)
        
    return f"/static/audio/{filename}"
