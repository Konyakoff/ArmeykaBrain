import json
import os

class PromptManager:
    """Управляет загрузкой и форматированием промптов для всех сервисов."""
    
    _core_prompts_cache = None
    _styles_cache = None
    _audio_prompts_cache = None

    @classmethod
    def _load_json(cls, filename: str) -> dict:
        path = os.path.join("prompts", filename)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    @classmethod
    def _save_json(cls, filename: str, data: dict) -> None:
        path = os.path.join("prompts", filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def invalidate_cache(cls) -> None:
        cls._core_prompts_cache = None
        cls._styles_cache = None
        cls._audio_prompts_cache = None

    @classmethod
    def get_core_prompts(cls) -> dict:
        if cls._core_prompts_cache is None:
            cls._core_prompts_cache = cls._load_json("core_prompts.json")
        return cls._core_prompts_cache

    @classmethod
    def get_styles(cls) -> dict:
        if cls._styles_cache is None:
            cls._styles_cache = cls._load_json("styles.json")
        return cls._styles_cache

    @classmethod
    def get_audio_prompts(cls) -> dict:
        if cls._audio_prompts_cache is None:
            cls._audio_prompts_cache = cls._load_json("prompts_audio.json")
        return cls._audio_prompts_cache

    @classmethod
    def get_step1_prompt(cls, question: str, combined_vyzhimki: str, override: str = None) -> str:
        template = override if override is not None else cls.get_core_prompts().get("step1", "")
        prompt = template.replace("[QUESTION]", question)
        prompt = prompt.replace("[VYZHIMKI]", combined_vyzhimki)
        return prompt

    @classmethod
    def get_step2_prompt(cls, question: str, combined_context: str, style: str, max_length: int,
                         override_style: str = None) -> str:
        styles_dict = cls.get_styles()
        # override_style заменяет только шаблон роли (system prompt), не всю обёртку
        system_prompt_template = override_style if override_style is not None else styles_dict.get(style, styles_dict.get("telegram_yur", ""))
        system_prompt = system_prompt_template.replace("{max_length}", str(max_length))
        
        template = cls.get_core_prompts().get("step2", "")
        prompt = template.replace("[SYSTEM_PROMPT]", system_prompt)
        prompt = prompt.replace("[QUESTION]", question)
        prompt = prompt.replace("[CONTEXT]", combined_context)
        return prompt

    @classmethod
    def get_audio_script_prompt(cls, expert_answer: str, duration: int, min_words: int, max_words: int,
                                override: str = None) -> str:
        prompts_dict = cls.get_audio_prompts()
        template = override if override is not None else prompts_dict.get("default", "Произошла ошибка загрузки промпта")
        
        prompt = template.replace("[ВСТАВИТЬ ВАШ ИСХОДНЫЙ ТЕКСТ]", expert_answer)
        prompt = prompt.replace("[N]", str(duration))
        prompt = prompt.replace("[MIN_WORDS]", str(min_words))
        prompt = prompt.replace("[MAX_WORDS]", str(max_words))
        # Для обратной совместимости
        prompt = prompt.replace("[N * 2]", str(min_words))
        prompt = prompt.replace("[N * 2.5]", str(max_words))
        
        return prompt

    @classmethod
    def get_audio_evaluation_prompt(cls, text: str, params: dict) -> str:
        prompts_dict = cls.get_audio_prompts()
        template = prompts_dict.get("evaluation", "Произошла ошибка загрузки промпта оценки")
        
        prompt = template.replace("[TEXT]", text)
        prompt = prompt.replace("[MODEL]", str(params.get("model", "")))
        prompt = prompt.replace("[VOICE]", str(params.get("voice", "")))
        prompt = prompt.replace("[STABILITY]", str(params.get("stability", "")))
        prompt = prompt.replace("[SIMILARITY]", str(params.get("similarity", "")))
        prompt = prompt.replace("[STYLE]", str(params.get("style", "")))
        prompt = prompt.replace("[BOOST]", str(params.get("use_speaker_boost", "")))
        
        return prompt

    # ──────────────────────────────────────────────────────────────
    # Сохранение промптов на диск

    SAVE_TARGETS = {
        "step3":       ("prompts_audio.json",  "default"),
        "step2_style": ("styles.json",          None),   # key приходит отдельно
        "step1":       ("core_prompts.json",    "step1"),
    }

    @classmethod
    def save_prompt(cls, target: str, content: str, style_key: str = None) -> None:
        """Сохраняет промпт в соответствующий JSON-файл и инвалидирует кэш."""
        if target not in cls.SAVE_TARGETS:
            raise ValueError(f"Неизвестный target: {target}")

        filename, key = cls.SAVE_TARGETS[target]

        if target == "step2_style":
            if not style_key:
                raise ValueError("style_key обязателен для target=step2_style")
            key = style_key

        data = cls._load_json(filename)
        data[key] = content
        cls._save_json(filename, data)
        cls.invalidate_cache()
