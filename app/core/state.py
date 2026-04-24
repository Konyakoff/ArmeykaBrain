"""Глобальное in-memory состояние приложения.

Содержит:
- background_tasks: набор активных asyncio.Task для предотвращения сборки GC.
- active_streams: словарь slug/node_id -> asyncio.Queue для SSE-стримов.

Вынесено в отдельный модуль, чтобы избежать циклических импортов
между разделёнными в PR3 router-модулями.
"""

from __future__ import annotations

import asyncio
from typing import Set

background_tasks: Set[asyncio.Task] = set()
active_streams: dict = {}
