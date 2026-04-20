import os
import json
import logging
import uuid
import aiohttp

from app.core.config import settings

logger = logging.getLogger("deepgram")

DEEPGRAM_API_URL = "https://api.deepgram.com/v1/listen"
DEEPGRAM_COST_PER_MIN = 0.0077  # Nova-3 Monolingual, Pay-As-You-Go


def _seconds_to_vtt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _utterances_to_vtt(utterances: list) -> str:
    lines = ["WEBVTT", ""]
    for i, u in enumerate(utterances, 1):
        start = _seconds_to_vtt_timestamp(u.get("start", 0))
        end = _seconds_to_vtt_timestamp(u.get("end", 0))
        transcript = u.get("transcript", "").strip()
        lines.append(str(i))
        lines.append(f"{start} --> {end}")
        lines.append(transcript)
        lines.append("")
    return "\n".join(lines)


async def generate_timecodes(audio_file_path: str) -> dict:
    """
    Отправляет локальный MP3 в Deepgram (Nova-3, ru), сохраняет:
      - static/audio/tc_{uuid}.json  — полный ответ Deepgram (words + utterances + paragraphs)
      - static/audio/tc_{uuid}.vtt   — субтитры WebVTT из utterances
    Возвращает:
      { json_url, vtt_url, cost, duration_sec }
    """
    api_key = settings.deepgram_api_key
    if not api_key:
        raise ValueError("DEEPGRAM_API_KEY не установлен в .env")

    # Нормализуем путь: /static/audio/... -> static/audio/...
    local_path = audio_file_path.lstrip("/")

    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Аудио файл не найден: {local_path}")

    params = {
        "model": "nova-3",
        "language": "ru",
        "smart_format": "true",
        "punctuate": "true",
        "paragraphs": "true",
        "utterances": "true",
    }

    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "audio/mpeg",
    }

    timeout = aiohttp.ClientTimeout(total=120)
    with open(local_path, "rb") as f:
        audio_bytes = f.read()

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            DEEPGRAM_API_URL,
            params=params,
            headers=headers,
            data=audio_bytes,
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise Exception(f"Deepgram API ошибка ({resp.status}): {error_text}")
            data = await resp.json()

    # Извлекаем данные
    metadata = data.get("metadata", {})
    duration_sec = round(metadata.get("duration", 0), 2)
    cost = round(duration_sec / 60 * DEEPGRAM_COST_PER_MIN, 6)

    results = data.get("results", {})
    channels = results.get("channels", [])
    utterances = results.get("utterances", [])

    # Сохраняем файлы
    uid = uuid.uuid4().hex[:8]
    audio_dir = os.path.join("static", "audio")
    os.makedirs(audio_dir, exist_ok=True)

    json_filename = f"tc_{uid}.json"
    vtt_filename = f"tc_{uid}.vtt"
    json_path = os.path.join(audio_dir, json_filename)
    vtt_path = os.path.join(audio_dir, vtt_filename)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    vtt_content = _utterances_to_vtt(utterances)
    with open(vtt_path, "w", encoding="utf-8") as f:
        f.write(vtt_content)

    logger.info(f"Deepgram: {duration_sec}s, ${cost:.6f}, saved {json_filename}")

    return {
        "json_url": f"/static/audio/{json_filename}",
        "vtt_url": f"/static/audio/{vtt_filename}",
        "cost": cost,
        "duration_sec": duration_sec,
    }
