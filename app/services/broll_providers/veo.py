"""
Google Veo B-roll provider via Gemini API.

Veo generates 8-second clips from text prompts.
Uses GEMINI_API_KEY (already configured).

Важные особенности API:
- Модель: veo-3.1-generate-001 (или veo-3.0-generate-001 как fallback)
- Endpoint: predictLongRunning — асинхронная операция
- Ответ содержит URI вида:
    https://generativelanguage.googleapis.com/v1beta/files/...
  Это Gemini Files API URI — нужно скачать через ?alt=media&key=...
- Итоговый файл сохраняется локально и отдаётся как публичный HTTPS URL
  /static/broll/{uuid}.mp4
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional

import aiohttp

from app.core.config import settings
from app.services.broll_providers.base import (
    BrollProvider,
    ClipResult,
    ProviderError,
    ProviderUnavailable,
)

logger = logging.getLogger("broll.veo")

PREDICT_URL   = "https://generativelanguage.googleapis.com/v1beta/models/{model}:predictLongRunning"
OPS_URL       = "https://generativelanguage.googleapis.com/v1beta/{name}"
DOWNLOAD_BASE = "https://generativelanguage.googleapis.com"

# Модели в порядке предпочтения: пробуем последнюю, при 404/400 — fallback
VEO_MODELS = ["veo-3.1-generate-preview", "veo-3.0-generate-001"]
VEO_COST_USD = 0.50  # ~оценка за 8-секундный клип

# Куда сохранять скачанные видео
BROLL_STATIC_DIR = Path("static/broll")
HOST_URL = "https://armeykabrain.net"


class VeoProvider:
    name = "veo"
    kind = "ai"

    def __init__(
        self,
        model: str | None = None,
        *,
        max_wait_sec: int = 300,
        poll_interval: int = 10,
    ):
        # model=None → будем перебирать VEO_MODELS автоматически
        self._model_override = model
        self.max_wait_sec   = max_wait_sec
        self.poll_interval  = poll_interval

    async def search(
        self,
        query: str,
        *,
        duration_sec: float,
        orientation: str = "portrait",
    ) -> Optional[ClipResult]:
        if not settings.gemini_api_key:
            raise ProviderUnavailable("GEMINI_API_KEY не задан в .env")

        BROLL_STATIC_DIR.mkdir(parents=True, exist_ok=True)

        aspect_ratio = (
            "9:16" if orientation == "portrait"
            else ("1:1" if orientation == "square" else "16:9")
        )

        models = [self._model_override] if self._model_override else VEO_MODELS

        last_error: Exception = ProviderError("Veo: нет доступных моделей")
        for model in models:
            try:
                op_name = await self._submit(model, query, aspect_ratio)
            except ProviderError as e:
                last_error = e
                # 404 -> fallback to next model
                if "404" in str(e) or "not found" in str(e).lower():
                    logger.warning(f"Veo model {model} недоступна, пробуем следующую: {e}")
                    continue
                # For 400 or other errors, raise immediately (e.g. rate limits or bad params)
                raise
            break
        else:
            raise last_error

        video_uri = await self._wait_for_video(op_name)
        if not video_uri:
            raise ProviderError("Veo: операция завершена, но URI видео не найден в ответе")

        public_url = await self._download_and_host(video_uri)

        w = 1080 if aspect_ratio in ("9:16", "1:1") else 1920
        h = 1920 if aspect_ratio == "9:16" else 1080

        return ClipResult(
            url=public_url,
            duration=8.0,
            width=w,
            height=h,
            license="Veo (Google)",
            source=self.name,
            query=query,
            cost_usd=VEO_COST_USD,
        )

    # ────────────────────────────────────────────────────────────────────────
    # Вспомогательные методы
    # ────────────────────────────────────────────────────────────────────────

    async def _submit(self, model: str, prompt: str, aspect_ratio: str) -> str:
        """Отправляет запрос генерации и возвращает operation name."""
        url    = PREDICT_URL.format(model=model)
        params = {"key": settings.gemini_api_key}
        body   = {
            "instances": [{"prompt": prompt}],
            "parameters": {
                "aspectRatio":       aspect_ratio,
                "durationSeconds":   8,
            },
        }
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, params=params, json=body) as resp:
                if resp.status in (401, 403):
                    raise ProviderUnavailable(
                        "Veo: нет доступа (API-ключ не имеет прав на Veo). "
                        "Убедитесь что Veo включён для данного ключа на ai.google.dev"
                    )
                if resp.status in (400, 404):
                    text = await resp.text()
                    raise ProviderError(f"Veo HTTP {resp.status} [{model}]: {text[:300]}")
                if resp.status != 200:
                    text = await resp.text()
                    raise ProviderError(f"Veo predict HTTP {resp.status}: {text[:200]}")
                op = await resp.json()

        op_name = op.get("name")
        if not op_name:
            raise ProviderError(f"Veo: операция не вернула name: {op}")
        return op_name

    async def _wait_for_video(self, op_name: str) -> Optional[str]:
        """Polling loop — ждём завершения Long Running Operation."""
        url     = OPS_URL.format(name=op_name)
        params  = {"key": settings.gemini_api_key}
        elapsed = 0
        # Отдельный таймаут на каждый HTTP-запрос (poll), а не на всю сессию
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while elapsed < self.max_wait_sec:
                await asyncio.sleep(self.poll_interval)
                elapsed += self.poll_interval

                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise ProviderError(f"Veo poll HTTP {resp.status}: {text[:200]}")
                    op = await resp.json()

                if not op.get("done"):
                    logger.debug(f"Veo: ждём {elapsed}с / {self.max_wait_sec}с ...")
                    continue

                err = op.get("error")
                if err:
                    raise ProviderError(
                        f"Veo: ошибка генерации — {err.get('message', 'unknown')}"
                    )

                response = op.get("response") or {}
                uri = self._extract_uri(response)
                if not uri:
                    logger.warning(
                        f"Veo: операция готова, URI не найден. response keys: {list(response.keys())}"
                    )
                return uri

        raise ProviderError(f"Veo: timeout {self.max_wait_sec}с — генерация не завершена")

    @staticmethod
    def _extract_uri(response: dict) -> Optional[str]:
        """Пробуем несколько возможных путей в ответе API."""
        
        # Разворачиваем вложенные структуры
        if "generateVideoResponse" in response:
            response = response["generateVideoResponse"]
        elif "predictResponse" in response:
            response = response["predictResponse"]
            
        # Путь 1: response.generatedVideos[0].video.uri  (основной)
        for key in ("generatedSamples", "generatedVideos", "generated_videos", "videos"):
            videos = response.get(key) or []
            if videos:
                first = videos[0]
                uri = (
                    (first.get("video") or {}).get("uri")
                    or first.get("uri")
                    or first.get("videoUri")
                    or first.get("video_uri")
                )
                if uri:
                    return uri

        # Путь 2: response.predictResponse[0].videoUri  (старый формат)
        for key in ("predictResponse", "predict_response"):
            pr = response.get(key) or []
            if pr and isinstance(pr, list) and pr[0]:
                uri = pr[0].get("videoUri") or pr[0].get("video_uri")
                if uri:
                    return uri

        return None

    async def _download_and_host(self, uri: str) -> str:
        """Скачивает видео по URI и сохраняет в static/broll/, возвращает HTTPS URL.

        Поддерживаемые форматы URI:
        - https://generativelanguage.googleapis.com/v1beta/files/... — Gemini Files API
        - gs://... — Cloud Storage (попытка через Files API redirect)
        - http(s):// — прямой URL (возвращаем как есть)
        """
        if not uri.startswith("http"):
            if uri.startswith("gs://"):
                raise ProviderError(
                    f"Veo вернул gs:// URI ({uri[:60]}...) — "
                    "для доступа нужны GCS credentials. "
                    "Убедитесь что проект настроен с Vertex AI или обновите до Veo 3.1."
                )
            raise ProviderError(f"Veo: неизвестный формат URI: {uri[:80]}")

        # Если URI — Gemini Files API, добавляем alt=media для скачивания
        if "generativelanguage.googleapis.com" in uri:
            download_url = uri
            if "alt=media" not in download_url:
                sep = "&" if "?" in download_url else "?"
                download_url = f"{download_url}{sep}alt=media&key={settings.gemini_api_key}"
        else:
            # Прямой публичный URL — не нужно ничего дополнительного
            logger.info(f"Veo: прямой URL, скачивание не требуется: {uri[:80]}")
            return uri

        logger.info(f"Veo: скачиваем видео из Gemini Files API ...")
        # Большой файл — используем длинный timeout
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(download_url) as resp:
                if resp.status == 403:
                    raise ProviderError(
                        "Veo: нет доступа к файлу (403). "
                        "API-ключ может не иметь доступа к Files API."
                    )
                if resp.status != 200:
                    text = await resp.text()
                    raise ProviderError(f"Veo download HTTP {resp.status}: {text[:200]}")

                content_type = resp.headers.get("content-type", "")
                if "video" not in content_type and "octet" not in content_type:
                    # Скорее всего вернулся JSON с ошибкой или метаданными
                    text = await resp.text()
                    raise ProviderError(
                        f"Veo: ожидался video/*, получен {content_type}: {text[:200]}"
                    )

                video_bytes = await resp.read()

        filename = f"{uuid.uuid4().hex}.mp4"
        filepath  = BROLL_STATIC_DIR / filename
        filepath.write_bytes(video_bytes)
        logger.info(f"Veo: сохранён {filepath} ({len(video_bytes)//1024} KB)")

        return f"{HOST_URL}/static/broll/{filename}"
