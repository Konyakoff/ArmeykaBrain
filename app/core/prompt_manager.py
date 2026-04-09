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
    def get_step1_prompt(cls, question: str, combined_vyzhimki: str) -> str:
        template = cls.get_core_prompts().get("step1", "")
        prompt = template.replace("[QUESTION]", question)
        prompt = prompt.replace("[VYZHIMKI]", combined_vyzhimki)
        return prompt

    @classmethod
    def get_step2_prompt(cls, question: str, combined_context: str, style: str, max_length: int) -> str:
        styles_dict = cls.get_styles()
        system_prompt_template = styles_dict.get(style, styles_dict.get("telegram_yur", ""))
        system_prompt = system_prompt_template.replace("{max_length}", str(max_length))
        
        template = cls.get_core_prompts().get("step2", "")
        prompt = template.replace("[SYSTEM_PROMPT]", system_prompt)
        prompt = prompt.replace("[QUESTION]", question)
        prompt = prompt.replace("[CONTEXT]", combined_context)
        return prompt

    @classmethod
    def get_audio_script_prompt(cls, expert_answer: str, duration: int, min_words: int, max_words: int) -> str:
        prompts_dict = cls.get_audio_prompts()
        template = prompts_dict.get("default", "Произошла ошибка загрузки промпта")
        
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
