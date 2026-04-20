import os
import aiohttp
import uuid
import subprocess
import json
import time
from app.core.config import settings

# Кэш для голосов, чтобы не запрашивать их каждый раз
_voices_cache = []
CACHE_FILE = "db/elevenlabs_voices_cache.json"
CACHE_TTL = 86400  # 24 часа в секундах

TRANSLATIONS = {
    "female": "женский",
    "male": "мужской",
    "neutral": "нейтральный",
    "young": "молодой",
    "middle_aged": "средний возраст",
    "middle aged": "средний возраст",
    "middle-aged": "средний возраст",
    "old": "пожилой",
    "calm": "спокойный",
    "casual": "повседневный",
    "chill": "расслабленный",
    "classy": "стильный",
    "confident": "уверенный",
    "crisp": "четкий",
    "cute": "милый",
    "formal": "формальный",
    "hyped": "хайповый",
    "mature": "зрелый",
    "professional": "профессиональный",
    "rough": "грубый",
    "sassy": "дерзкий",
    "upbeat": "бодрый",
    "advertisement": "реклама",
    "characters_animation": "анимация",
    "conversational": "разговорный",
    "entertainment_tv": "развлечения",
    "informative_educational": "обучающий",
    "narrative_story": "повествование",
    "social_media": "соцсети",
    "video_games": "игры",
    "news": "новости",
    "animation": "анимация",
    "interactive": "интерактивный",
    "children": "для детей",
    "narration": "озвучка",
    "audiobook": "аудиокнига",
    "laid-back": "непринужденный",
    "resonant": "звонкий",
    "reassuring": "обнадеживающий",
    "enthusiast": "энтузиаст",
    "quirky attitude": "необычный характер",
    "quirky": "причудливый",
    "attitude": "характер",
    "deep": "глубокий",
    "energetic": "энергичный",
    "warm": "теплый",
    "captivating storyteller": "увлекательный рассказчик",
    "captivating": "увлекательный",
    "storyteller": "рассказчик",
    "husky trickster": "хриплый шутник",
    "husky": "хриплый",
    "trickster": "шутник",
    "relaxed": "расслабленный",
    "informative": "информативный",
    "fierce warrior": "свирепый воин",
    "fierce": "свирепый",
    "warrior": "воин",
    "social media creator": "создатель контента",
    "creator": "создатель",
    "clear": "ясный",
    "engaging educator": "увлекательный преподаватель",
    "engaging": "увлекательный",
    "educator": "преподаватель",
    "knowledgable": "знающий",
    "relaxed optimist": "расслабленный оптимист",
    "optimist": "оптимист",
    "playful": "игривый",
    "bright": "яркий",
    "smooth": "плавный",
    "trustworthy": "надежный",
    "charming": "обаятельный",
    "down-to-earth": "приземленный",
    "resonant and comforting": "звонкий и утешающий",
    "comforting": "утешающий",
    "steady broadcaster": "стабильный диктор",
    "steady": "стабильный",
    "broadcaster": "диктор",
    "velvety actress": "бархатная актриса",
    "velvety": "бархатный",
    "actress": "актриса",
    "dominant": "доминантный",
    "firm": "твердый",
    "wise": "мудрый",
    "balanced": "сбалансированный"
}

def translate_label(label: str) -> str:
    if not label:
        return ""
    # label может быть как "middle_aged", так и "Middle Aged"
    # Иногда это комбинации, например "calm, confident"
    parts = [p.strip() for p in label.split(",")]
    translated_parts = []
    for p in parts:
        key = p.lower().replace(" ", "_")
        if key in TRANSLATIONS:
            translated_parts.append(TRANSLATIONS[key])
        else:
            # пробуем поискать ключ с пробелом
            key2 = p.lower()
            if key2 in TRANSLATIONS:
                translated_parts.append(TRANSLATIONS[key2])
            else:
                translated_parts.append(p)
    return ", ".join(translated_parts)

async def get_elevenlabs_voices() -> list:
    """Возвращает голоса из in-memory кэша или файла. Без автообновления по TTL."""
    global _voices_cache
    if _voices_cache:
        return _voices_cache

    # Всегда читаем из файла (без проверки возраста)
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _voices_cache = json.load(f)
                return _voices_cache
        except Exception as e:
            print(f"Ошибка чтения кэша ElevenLabs: {e}")

    return []


async def _fetch_elevenlabs_voices_from_api() -> list:
    """Загружает свежие голоса из ElevenLabs API. Используется только при явном обновлении."""
    api_key = settings.elevenlabs_api_key
    if not api_key:
        return []

    url = "https://api.elevenlabs.io/v1/voices"
    headers = {
        "Accept": "application/json",
        "xi-api-key": api_key
    }

    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    voices = data.get("voices", [])
                    extracted = []
                    for v in voices:
                        orig_name = v.get("name", "")
                        name_parts = orig_name.split(" - ", 1)
                        if len(name_parts) == 2:
                            human_name = name_parts[0]
                            desc_to_translate = name_parts[1].replace(" and ", ", ")
                            translated_desc = translate_label(desc_to_translate)
                            final_name = f"{human_name} - {translated_desc}" if translated_desc else orig_name
                        else:
                            final_name = orig_name

                        labels = v.get("labels", {})
                        gender = translate_label(labels.get("gender", ""))
                        age = translate_label(labels.get("age", ""))
                        descriptive = translate_label(labels.get("descriptive", ""))
                        use_case = translate_label(labels.get("use_case", ""))

                        desc_parts = [p for p in [gender, age, descriptive, use_case] if p]
                        desc_str = ", ".join(desc_parts)

                        raw_category = v.get("category", "premade")
                        is_my_voice = raw_category in ("cloned", "professional", "generated")
                        category = "my" if is_my_voice else "public"

                        extracted.append({
                            "voice_id": v.get("voice_id"),
                            "name": final_name,
                            "description": desc_str,
                            "category": category
                        })

                    # Сохраняем в кэш-файл и обновляем in-memory
                    try:
                        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
                        with open(CACHE_FILE, "w", encoding="utf-8") as f:
                            json.dump(extracted, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        print(f"Ошибка записи кэша ElevenLabs: {e}")

                    global _voices_cache
                    _voices_cache = extracted
                    return extracted
    except Exception as e:
        print(f"Error fetching ElevenLabs voices: {e}")
    return []

async def generate_audio(text: str, model_id: str, voice_id: str = "pFZP5JQG7iQjIQuC4Bku", speed: float = 1.0, stability: float = 0.5, similarity_boost: float = 0.75, style: float = 0.25, use_speaker_boost: bool = True) -> tuple:
    """
    Генерирует аудио из текста с помощью ElevenLabs API и сохраняет в файл.
    Возвращает кортеж (URL_web_версии, URL_оригинальной_версии).
    """
    api_key = settings.elevenlabs_api_key
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY не установлен в .env")
        
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key
    }
    
    # Remove technical pause from text (handled via ffmpeg now)
    
    # Ensure speed is clamped between 0.7 and 1.2 as required by ElevenLabs API
    safe_speed = max(0.7, min(speed, 1.2))
    
    data = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
            "use_speaker_boost": use_speaker_boost,
            "speed": safe_speed
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
    uuid_str = uuid.uuid4().hex[:8]
    filename_orig = f"audio_{uuid_str}_orig.mp3"
    filepath_orig = os.path.join(audio_dir, filename_orig)
    
    with open(filepath_orig, "wb") as f:
        f.write(audio_content)
        
    filename_web = f"audio_{uuid_str}_web.mp3"
    filepath_web = os.path.join(audio_dir, filename_web)
    
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", filepath_orig, "-af", "adelay=1000|1000", filepath_web],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        print(f"Error adding silence via ffmpeg: {e}")
        filename_web = filename_orig
        
    return f"/static/audio/{filename_web}", f"/static/audio/{filename_orig}"
