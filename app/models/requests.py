"""Pydantic-модели запросов API.

Вынесены из app/main.py в рамках PR3, чтобы router-модули могли импортировать
их без циклических зависимостей.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Текст вопроса")
    model: str = Field(default="gemini-3.1-pro-preview", description="Название модели (общий fallback)")
    model1: Optional[str] = Field(default=None, description="Модель для шага 1 (подбор статей)")
    model2: Optional[str] = Field(default=None, description="Модель для шага 2 (экспертная статья)")
    model3: Optional[str] = Field(default=None, description="Модель для шага 3 (аудио-сценарий)")
    style: str = Field(default="telegram_yur", description="Стиль ответа")
    context_threshold: int = Field(default=70, ge=0, le=100, description="Порог контекста (%)")
    max_length: int = Field(default=4000, description="Максимальная длина ответа в символах")
    send_prompts: bool = Field(default=False, description="Возвращать ли тексты промптов")
    audio_duration: int = Field(default=30, ge=14, le=300, description="Длительность аудио в секундах")
    tab_type: str = Field(default="text", description="Тип вкладки (text или audio)")
    elevenlabs_model: str = Field(default="eleven_v3", description="Модель ElevenLabs для озвучки")
    audio_wpm: int = Field(default=150, ge=100, le=250, description="Слов в минуту")
    elevenlabs_voice: str = Field(default="FGY2WhTYpPnroxEErjIq", description="Голос ElevenLabs")
    audio_style: float = Field(default=0.25, ge=0.0, le=1.0, description="Стиль (Style)")
    use_speaker_boost: bool = Field(default=True, description="Использовать Speaker Boost")
    audio_stability: float = Field(default=0.5, ge=0.0, le=1.0, description="Stability")
    audio_similarity_boost: float = Field(default=0.75, ge=0.0, le=1.0, description="Similarity Boost")
    heygen_avatar_id: str = Field(default="Abigail_standing_office_front", description="ID аватара HeyGen")
    video_format: str = Field(default="16:9", description="Формат видео: 16:9, 9:16, 1:1")
    heygen_engine: str = Field(default="avatar_iv", description="Версия движка: avatar_iv, avatar_iii")
    avatar_style: str = Field(default="auto", description="Стиль кадрирования: auto | normal | closeUp | circle")
    custom_prompts: Optional[dict] = Field(default=None, description="Кастомные шаблоны промптов для текущего запроса")
    audio_prompt_name: Optional[str] = Field(default=None, description="Имя выбранного аудио-сценарий промпта (step3)")


class AudioRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Текст для озвучки")
    elevenlabs_model: str = Field(default="eleven_v3", description="Модель ElevenLabs")
    elevenlabs_voice: str = Field(default="FGY2WhTYpPnroxEErjIq", description="Голос ElevenLabs")
    audio_wpm: int = Field(default=150, ge=100, le=250, description="Скорость в словах в минуту")
    stability: float = Field(default=0.5, ge=0.0, le=1.0, description="Stability")
    similarity_boost: float = Field(default=0.75, ge=0.0, le=1.0, description="Similarity Boost")
    style: float = Field(default=0.25, ge=0.0, le=1.0, description="Style")
    use_speaker_boost: bool = Field(default=True, description="Использовать Speaker Boost")
    slug: str = Field(default=None, description="Slug для привязки к результату")


class UpgradeAudioRequest(BaseModel):
    slug: str = Field(..., description="Slug результата для апгрейда")
    audio_duration: int = Field(default=60, ge=14, le=300, description="Длительность аудио в секундах")
    elevenlabs_model: str = Field(default="eleven_v3", description="Модель ElevenLabs")
    audio_wpm: int = Field(default=150, ge=100, le=250, description="Скорость в словах в минуту")
    elevenlabs_voice: str = Field(default="FGY2WhTYpPnroxEErjIq", description="Голос ElevenLabs")
    audio_style: float = Field(default=0.25, ge=0.0, le=1.0, description="Style")
    use_speaker_boost: bool = Field(default=True, description="Speaker Boost")
    audio_stability: float = Field(default=0.5, ge=0.0, le=1.0, description="Stability")
    audio_similarity_boost: float = Field(default=0.75, ge=0.0, le=1.0, description="Similarity Boost")
    generate_video: bool = Field(default=False, description="Создать также видео (Шаг 5)")
    heygen_avatar_id: str = Field(default="Abigail_standing_office_front", description="ID аватара HeyGen")
    video_format: str = Field(default="16:9", description="Формат видео: 16:9, 9:16, 1:1")
    heygen_engine: str = Field(default="avatar_iv", description="Версия движка: avatar_iv, avatar_iii")
    avatar_style: str = Field(default="auto", description="Стиль кадрирования: auto | normal | closeUp | circle")


class GenerateVideoRequest(BaseModel):
    slug: str = Field(..., description="Slug результата")
    audio_url: str = Field(..., description="Путь до аудиофайла")
    heygen_engine: str = Field(default="avatar_iv", description="Версия движка HeyGen")
    video_format: str = Field(default="16:9", description="Формат видео")
    heygen_avatar_id: str = Field(..., description="ID аватара HeyGen")
    avatar_style: str = Field(default="auto", description="Стиль кадрирования: auto | normal | closeUp | circle")
    is_main: bool = Field(default=True, description="Является ли это основным аудио")


class EvaluateRequest(BaseModel):
    audio_url: str = Field(..., description="Путь до аудиофайла")
    text: str = Field(..., description="Текст для озвучки")
    elevenlabs_model: str = Field(default="eleven_v3", description="Модель ElevenLabs")
    elevenlabs_voice: str = Field(default="FGY2WhTYpPnroxEErjIq", description="Голос ElevenLabs")
    stability: float = Field(default=0.5, description="Stability")
    similarity_boost: float = Field(default=0.75, description="Similarity Boost")
    style: float = Field(default=0.25, description="Style")
    use_speaker_boost: bool = Field(default=True, description="Speaker Boost")
    slug: str = Field(default=None, description="Slug результата")
    is_main: bool = Field(default=True, description="Основное ли это аудио")


class SavePromptRequest(BaseModel):
    target: str
    content: str
    style_key: Optional[str] = None
    password: Optional[str] = None


class CreatePromptRequest(BaseModel):
    target: str
    name: str
    content: str
    password: Optional[str] = None


class DeletePromptRequest(BaseModel):
    target: str
    name: str
    password: Optional[str] = None


class GenerateNodeRequest(BaseModel):
    target_type: str = Field(..., description="script | audio | video")
    params: dict = Field(default_factory=dict)


class RenamNodeRequest(BaseModel):
    title: str
