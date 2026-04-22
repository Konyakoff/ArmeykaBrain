"""
Claude API service — аналог gemini_service.py для шагов 1, 2 и 3.
Использует библиотеку anthropic (официальный SDK Anthropic).
"""
import json
import re
import os
import glob
import asyncio
from anthropic import AsyncAnthropic
from app.services.data_loader import ALL_MODELS, find_rag_context
from app.core.config import settings
from app.models.schemas import ArticleItem, Step1Result, Step2Result, Step3Result
from app.core.prompt_manager import PromptManager

_client: AsyncAnthropic | None = None

def get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


def get_claude_model_info(model_name: str) -> dict | None:
    for m in ALL_MODELS:
        if m["model_name"] == model_name:
            return m
    return None


def calculate_claude_cost(input_tokens: int, output_tokens: int, model_name: str) -> tuple[float, float]:
    info = get_claude_model_info(model_name)
    if not info:
        return 0.0, 0.0
    in_cost  = (input_tokens  / 1_000_000) * info["price_per_1m_input"]
    out_cost = (output_tokens / 1_000_000) * info["price_per_1m_output"]
    return in_cost, out_cost


async def _call_claude(model_name: str, prompt: str, temperature: float = 0.3,
                       max_tokens: int = 8192, json_mode: bool = False) -> tuple[str, int, int]:
    """
    Выполняет один вызов Claude API.
    Возвращает (text, input_tokens, output_tokens).
    """
    client = get_client()
    system_msg = (
        "You are a professional legal AI assistant. "
        "Always respond in the same language as the user's question. "
        + ("Respond ONLY with valid JSON, no markdown, no explanation." if json_mode else "")
    )
    response = await client.messages.create(
        model=model_name,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_msg,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text
    in_tok  = response.usage.input_tokens
    out_tok = response.usage.output_tokens
    return text, in_tok, out_tok


# ─── Шаг 1: поиск релевантных статей ──────────────────────────────────────────

async def get_top_ids_claude(question: str, model_name: str) -> Step1Result:
    """Шаг 1 через Claude: ищет ТОП-15 статей из выжимок."""
    vyzhimka_dir = os.path.join("data", "Short_Zakony_Vyzhimka")
    all_contexts = []
    for file_path in glob.glob(os.path.join(vyzhimka_dir, "*.txt")):
        file_name = os.path.basename(file_path)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                all_contexts.append(
                    f"--- НАЧАЛО ДОКУМЕНТА: {file_name} ---\n{content}\n--- КОНЕЦ ДОКУМЕНТА: {file_name} ---\n"
                )
        except Exception as e:
            print(f"Ошибка чтения {file_path}: {e}")

    combined_vyzhimki = "\n".join(all_contexts)
    prompt = PromptManager.get_step1_prompt(question, combined_vyzhimki)

    try:
        raw_text, in_tok, out_tok = await _call_claude(
            model_name, prompt, temperature=0.1, max_tokens=4096, json_mode=True
        )

        # Очистка и парсинг JSON
        raw_text = re.sub(r'^```json\s*', '', raw_text.strip())
        raw_text = re.sub(r'\s*```$', '', raw_text)
        data = json.loads(raw_text)

        if isinstance(data, list):
            articles_data = data
            query_category = "unknown"
        else:
            articles_data = data.get("top_articles", [])
            query_category = data.get("query_category", "unknown")

        top_articles = []
        for item in articles_data[:15]:
            file_name = item.get("file_name", "").replace(".txt", "")
            item_number_raw = str(item.get("item_number", ""))
            match = re.search(r'\d+(?:[.-]\d+)*', item_number_raw)
            item_number = match.group(0) if match else item_number_raw
            section    = str(item.get("section", "")).strip()
            subsection = str(item.get("subsection", "")).strip()
            percent    = item.get("percent", 0)
            if file_name and item_number:
                top_articles.append(ArticleItem(
                    file_name=file_name, section=section, subsection=subsection,
                    item_number=item_number, percent=percent
                ))

        # Форсируем расписание болезней в топ для medical/mixed
        if query_category in ["medical", "mixed"]:
            rasp = [a for a in top_articles if "3.PP_565_RaspBolezney" in a.file_name]
            for i, a in enumerate(rasp[:3]):
                a.percent = [95, 94, 93][i]
            top_articles.sort(key=lambda x: x.percent, reverse=True)

        return Step1Result(
            articles=top_articles,
            query_category=query_category,
            in_tokens=in_tok,
            out_tokens=out_tok,
            prompt=prompt,
        )

    except Exception as e:
        print(f"Error in get_top_ids_claude: {e}")
        return Step1Result(articles=[], query_category="unknown", error=str(e))


# ─── Шаг 2: экспертный анализ ────────────────────────────────────────────────

async def get_expert_analysis_claude(question: str, combined_context: str,
                                     style: str = "telegram_yur", max_length: int = 4000,
                                     override_style: str = None,
                                     model_name: str = "claude-sonnet-4-6") -> Step2Result:
    """Шаг 2 через Claude: формирует экспертное заключение."""
    if not combined_context:
        return Step2Result(answer="К сожалению, не удалось найти детальный юридический контекст.")

    prompt = PromptManager.get_step2_prompt(question, combined_context, style, max_length,
                                            override_style=override_style)
    try:
        text, in_tok, out_tok = await _call_claude(
            model_name, prompt, temperature=0.3,
            max_tokens=min(max_length * 2, 8192)
        )
        return Step2Result(answer=text, in_tokens=in_tok, out_tokens=out_tok, prompt=prompt)
    except Exception as e:
        print(f"Error in get_expert_analysis_claude: {e}")
        return Step2Result(answer=f"Ошибка при генерации ответа: {e}", error=str(e))


# ─── Шаг 3: аудиосценарий ────────────────────────────────────────────────────

async def generate_audio_script_claude(expert_answer: str, duration: int, wpm: int = 150,
                                       override: str = None,
                                       model_name: str = "claude-haiku-4-5") -> Step3Result:
    """Шаг 3 через Claude: генерирует короткий аудиосценарий."""
    if not expert_answer:
        return Step3Result(script="Нет текста для обработки.")

    clamped_speed       = max(0.7, min(wpm / 150.0, 1.2))
    target_effective_wpm = 130.0 * clamped_speed
    words_per_second    = target_effective_wpm / 60.0
    min_words           = int(duration * words_per_second * 0.85)
    max_words           = int(duration * words_per_second * 1.0)

    prompt = PromptManager.get_audio_script_prompt(expert_answer, duration, min_words, max_words,
                                                   override=override)
    try:
        text, in_tok, out_tok = await _call_claude(
            model_name, prompt, temperature=0.4, max_tokens=4096
        )
        return Step3Result(script=text, in_tokens=in_tok, out_tokens=out_tok, prompt=prompt)
    except Exception as e:
        print(f"Error in generate_audio_script_claude: {e}")
        return Step3Result(script=f"Ошибка при генерации аудио сценария: {e}", error=str(e))
