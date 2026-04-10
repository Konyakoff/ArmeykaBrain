import os
import aiohttp
import asyncio
import logging
import json
import time
from app.core.config import settings

logger = logging.getLogger("heygen")

CACHE_FILE = "db/heygen_avatars_cache.json"
CACHE_TTL = 86400  # 24 часа

HEYGEN_API_URL = "https://api.heygen.com"
HEADERS = {
    "X-Api-Key": settings.heygen_api_key,
    "Content-Type": "application/json",
    "Accept": "application/json"
}

_avatars_cache = None

async def _download_avatar_image(session, avatar_id, image_url, semaphore):
    local_dir = os.path.join("static", "img", "avatars")
    local_path = os.path.join(local_dir, f"{avatar_id}.webp")
    if os.path.exists(local_path):
        return
    async with semaphore:
        try:
            async with session.get(image_url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    with open(local_path, "wb") as f:
                        f.write(data)
        except Exception as e:
            logger.error(f"Failed to download image for {avatar_id}: {e}")

async def sync_avatars_images(avatars):
    local_dir = os.path.join("static", "img", "avatars")
    os.makedirs(local_dir, exist_ok=True)
    semaphore = asyncio.Semaphore(10)
    async with aiohttp.ClientSession() as session:
        tasks = []
        for a in avatars:
            url = a.get("_original_image_url")
            if url and url.startswith("http"):
                tasks.append(_download_avatar_image(session, a["avatar_id"], url, semaphore))
        if tasks:
            await asyncio.gather(*tasks)

def translate_avatar_name(name: str, gender: str) -> str:
    """Переводит и форматирует имя аватара для удобного отображения."""
    gender_ru = "жен." if gender == "female" else "муж." if gender == "male" else ""
    
    desc = name
    # Базовые переводы окружения и одежды
    translations = {
        "Upper Body": "По пояс",
        "Office Front": "Офис, анфас",
        "Office Side": "Офис, сбоку",
        "Sofa Front": "На диване, анфас",
        "Sofa Side": "На диване, сбоку",
        "in Brown blazer": "в коричневом пиджаке",
        "in Blue blazer": "в синем пиджаке",
        "in Beige blazer": "в бежевом пиджаке",
        "in Black blazer": "в черном пиджаке",
        "in Blue shirt": "в синей рубашке",
        "in White shirt": "в белой рубашке",
        "in Black shirt": "в черной рубашке",
        "in Blue t-shirt": "в синей футболке",
        "in Black t-shirt": "в черной футболке",
        "in White t-shirt": "в белой футболке",
        "in Grey t-shirt": "в серой футболке",
        "in Grey sweater": "в сером свитере",
        "in Black sweater": "в черном свитере"
    }
    
    for eng, ru in translations.items():
        desc = desc.replace(eng, ru)
    
    # Очищаем от лишних скобок
    desc = desc.replace("(", "").replace(")", "").strip()
    
    # Пытаемся вычленить имя (обычно идет первым словом)
    parts = desc.split(" ", 1)
    if len(parts) > 1:
        first_name = parts[0]
        rest = parts[1]
        return f"{first_name} ({gender_ru}, {rest})"
    
    return f"{desc} ({gender_ru})"

async def get_heygen_avatars():
    """Получает список доступных аватаров."""
    global _avatars_cache
    if _avatars_cache is not None:
        return _avatars_cache
        
    # Пытаемся загрузить из кэш-файла
    if os.path.exists(CACHE_FILE):
        file_age = time.time() - os.path.getmtime(CACHE_FILE)
        if file_age < CACHE_TTL:
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    _avatars_cache = json.load(f)
                    return _avatars_cache
            except Exception as e:
                logger.error(f"Ошибка чтения кэша HeyGen: {e}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{HEYGEN_API_URL}/v2/avatars", headers=HEADERS) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    avatars = []
                    for avatar in data.get("data", {}).get("avatars", []):
                        name = avatar.get("avatar_name", "")
                        gender = avatar.get("gender", "")
                        
                        name_lower = name.lower()
                        id_lower = avatar.get("avatar_id", "").lower()
                        combined = name_lower + " " + id_lower
                        
                        # Все аватары подходят для горизонтального и квадратного форматов.
                        # При closeUp-стиле любой аватар можно использовать вертикально,
                        # но is_vertical_friendly=True означает "хорошо смотрится без closeUp".
                        is_horizontal = True
                        is_square = True
                        
                        # Признаки крупного плана / портрета — хорошо для вертикального 9:16
                        CLOSEUP_KEYWORDS = [
                            "upper body", "по пояс", "close", "head", "bust", "portrait",
                            "expressive", "face", "vertical", "mobile"
                        ]
                        # Признаки полноростового или широкого кадра — плохо для 9:16 без closeUp
                        FULLBODY_KEYWORDS = [
                            "standing", "sofa", "walk", "full body",
                            "biztalk", "business_front", "business_side",
                            "nurse_front", "nurse_side", "biz_front",
                            "suit", "sitting_side", "sitting_front"
                        ]
                        
                        is_vertical = False
                        if any(k in combined for k in CLOSEUP_KEYWORDS):
                            is_vertical = True
                        elif any(k in combined for k in FULLBODY_KEYWORDS):
                            is_vertical = False
                        elif any(ch.isdigit() for ch in id_lower) and "standing" not in id_lower:
                            # Аватары с датой в ID (новые Studio Avatars) без явного fullbody — как правило, portrait-friendly
                            is_vertical = True
                        
                        avatars.append({
                            "avatar_id": avatar.get("avatar_id"),
                            "avatar_name": translate_avatar_name(name, gender),
                            "gender": gender,
                            "_original_image_url": avatar.get("preview_image_url"),
                            "preview_image_url": f"/api/avatar-preview/{avatar.get('avatar_id')}",
                            "preview_video_url": "",
                            "is_horizontal_friendly": is_horizontal,
                            "is_vertical_friendly": is_vertical,
                            "is_square_friendly": is_square
                        })
                    _avatars_cache = avatars
                    
                    # Запускаем фоновую загрузку картинок
                    asyncio.create_task(sync_avatars_images(avatars))
                    
                    # Сохраняем в кэш-файл
                    try:
                        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
                        with open(CACHE_FILE, "w", encoding="utf-8") as f:
                            json.dump(_avatars_cache, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        logger.error(f"Ошибка записи кэша HeyGen: {e}")
                        
                    return avatars
                else:
                    logger.error(f"Error fetching avatars: {await resp.text()}")
                    return []
    except Exception as e:
        logger.error(f"HeyGen get_avatars error: {e}")
        return []

async def generate_video_from_audio(
    avatar_id: str,
    audio_url: str,
    title: str = "Video",
    video_format: str = "16:9",
    heygen_engine: str = "avatar_iv",
    avatar_style: str = "auto"
):
    """
    Отправляет запрос на генерацию видео в HeyGen V2.
    avatar_style: "auto" | "normal" | "closeUp" | "circle"
    При "auto" стиль определяется по video_format: 9:16/1:1 → closeUp, 16:9 → normal.
    """
    
    # Определяем размеры видео
    if video_format == "9:16":
        dimension = {"width": 1080, "height": 1920}
    elif video_format == "1:1":
        dimension = {"width": 1080, "height": 1080}
    else:
        dimension = {"width": 1920, "height": 1080}

    # Определяем стиль кадрирования.
    # closeUp — нативный механизм HeyGen для portrait/vertical: делает face-centered crop
    # для любого аватара без хаков со scale/offset.
    if avatar_style == "auto":
        resolved_style = "closeUp" if video_format in ("9:16", "1:1") else "normal"
    else:
        resolved_style = avatar_style  # используем явный выбор пользователя

    # Фон: тёмный для вертикального/квадратного (смотрится профессиональнее),
    # нейтральный для горизонтального
    bg_color = "#1a1a2e" if video_format in ("9:16", "1:1") else "#F0F0F0"

    payload = {
        "title": title,
        "dimension": dimension,
        "video_inputs": [
            {
                "character": {
                    "type": "avatar",
                    "avatar_id": avatar_id,
                    "avatar_style": resolved_style,
                    "use_avatar_iv_model": heygen_engine == "avatar_iv",
                    "scale": 1.0,
                    "offset": {"x": 0.0, "y": 0.0}
                },
                "voice": {
                    "type": "audio",
                    "audio_url": audio_url
                },
                "background": {
                    "type": "color",
                    "value": bg_color
                }
            }
        ]
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{HEYGEN_API_URL}/v2/video/generate", headers=HEADERS, json=payload) as resp:
                data = await resp.json()
                if resp.status == 200 and data.get("data") and data["data"].get("video_id"):
                    return data["data"]["video_id"]
                else:
                    error_msg = data.get("error", {}).get("message") if data.get("error") else str(data)
                    raise Exception(f"HeyGen API Error: {error_msg}")
    except Exception as e:
        logger.error(f"HeyGen generate_video error: {e}")
        raise

async def check_video_status(video_id: str):
    """
    Проверяет статус видео. Возвращает dict со статусом и url.
    Статусы: 'pending', 'processing', 'completed', 'failed'
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{HEYGEN_API_URL}/v1/video_status.get", headers=HEADERS, params={"video_id": video_id}) as resp:
                data = await resp.json()
                if resp.status == 200 and data.get("data"):
                    status = data["data"].get("status")
                    video_url = data["data"].get("video_url")
                    error = data["data"].get("error")
                    return {
                        "status": status,
                        "video_url": video_url,
                        "error": error
                    }
                else:
                    error_msg = data.get("error", {}).get("message") if data.get("error") else str(data)
                    raise Exception(f"HeyGen API Error: {error_msg}")
    except Exception as e:
        logger.error(f"HeyGen check_status error: {e}")
        raise

def calculate_heygen_cost(duration_sec: int, heygen_engine: str) -> float:
    import math
    # 0.5 API credits per 30 seconds
    minutes = max(0.5, math.ceil(duration_sec / 30) * 0.5)
    # Avatar IV consumes 6 credits per minute. Avatar III consumes 1 credit per minute.
    credits_per_min = 6 if heygen_engine == "avatar_iv" else 1
    total_credits = minutes * credits_per_min
    # Assume $0.15 per API credit based on generic pricing estimation
    cost_per_credit = 0.15
    return total_credits * cost_per_credit
