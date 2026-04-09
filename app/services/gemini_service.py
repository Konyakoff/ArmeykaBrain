import google.generativeai as genai
import json
import re
import os
import glob
from app.services.data_loader import JSON_DB, GEMINI_MODELS, find_rag_context
from app.core.config import settings
from app.models.schemas import ArticleItem, Step1Result, Step2Result, Step3Result
from app.core.prompt_manager import PromptManager

# Настройка API
genai.configure(api_key=settings.gemini_api_key)

def get_model_info(model_name: str) -> dict:
    for m in GEMINI_MODELS:
        if m["model_name"] == model_name:
            return m
    return None

def calculate_cost(input_tokens: int, output_tokens: int, model_name: str) -> tuple:
    info = get_model_info(model_name)
    if not info:
        return 0.0, 0.0
    
    input_cost = (input_tokens / 1_000_000) * info["price_per_1m_input"]
    output_cost = (output_tokens / 1_000_000) * info["price_per_1m_output"]
    return input_cost, output_cost

async def get_top_ids(question: str, selected_model: str) -> Step1Result:
    """Шаг 1: Получаем ТОП-15 статей/пунктов закона из выжимок."""
    model = genai.GenerativeModel(selected_model)
    
    # Читаем все txt файлы из папки выжимок
    vyzhimka_dir = os.path.join("data", "Short_Zakony_Vyzhimka")
    all_contexts = []
    
    for file_path in glob.glob(os.path.join(vyzhimka_dir, "*.txt")):
        file_name = os.path.basename(file_path)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                all_contexts.append(f"--- НАЧАЛО ДОКУМЕНТА: {file_name} ---\n{content}\n--- КОНЕЦ ДОКУМЕНТА: {file_name} ---\n")
        except Exception as e:
            print(f"Ошибка чтения {file_path}: {e}")
            
    combined_vyzhimki = "\n".join(all_contexts)
    
    prompt = PromptManager.get_step1_prompt(question, combined_vyzhimki)
    try:
        response = await model.generate_content_async(
            prompt,
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.1,
            )
        )
        
        # Очистка и парсинг JSON
        raw_response = re.sub(r'^```json\s*', '', response.text.strip())
        raw_response = re.sub(r'\s*```$', '', raw_response)
        data = json.loads(raw_response)
        
        # Если модель вернула старый формат (просто список) вместо словаря
        if isinstance(data, list):
            articles_data = data
            query_category = "unknown"
        else:
            articles_data = data.get("top_articles", [])
            query_category = data.get("query_category", "unknown")
        
        # Извлекаем данные
        top_articles = []
        for item in articles_data[:15]:
            file_name = item.get("file_name", "").replace(".txt", "")
            item_number_raw = str(item.get("item_number", ""))
            
            # Извлекаем только сам номер (убираем слова "Статья", "Пункт", пробелы)
            # Например, из "Статья 42" получим "42", из "Пункт 5.1" -> "5.1", из "6.1-1" -> "6.1-1"
            match = re.search(r'\d+(?:[.-]\d+)*', item_number_raw)
            item_number = match.group(0) if match else item_number_raw
            
            section = str(item.get("section", "")).strip()
            subsection = str(item.get("subsection", "")).strip()
            percent = item.get("percent", 0)
            
            if file_name and item_number:
                top_articles.append(ArticleItem(
                    file_name=file_name,
                    section=section,
                    subsection=subsection,
                    item_number=item_number,
                    percent=percent
                ))
                
        # --- ФОРСИРОВАНИЕ РАСПИСАНИЯ БОЛЕЗНЕЙ В ТОП ---
        if query_category in ["medical", "mixed"]:
            rasp_articles = [a for a in top_articles if "3.PP_565_RaspBolezney" in a.file_name]
            percents = [95, 94, 93]
            for i, a in enumerate(rasp_articles[:3]):
                a.percent = percents[i]
            
            # Сортируем заново, чтобы измененные статьи всплыли на самый верх
            top_articles.sort(key=lambda x: x.percent, reverse=True)
                
        usage = response.usage_metadata
        return Step1Result(
            articles=top_articles,
            query_category=query_category,
            usage=usage,
            in_tokens=usage.prompt_token_count,
            out_tokens=usage.candidates_token_count,
            prompt=prompt
        )
        
    except Exception as e:
        print(f"Error in get_top_ids: {e}")
        # Возвращаем ошибку
        return Step1Result(articles=[], query_category="unknown", error=str(e))

def prepare_expert_context(top_articles: list[ArticleItem], threshold: int = 70) -> tuple:
    """Подготавливает контекст для второго шага и возвращает (combined_context, used_ids)."""
    # Фильтруем статьи: берем только те, где вероятность >= threshold
    filtered_articles = [art for art in top_articles if art.percent >= threshold]
    
    # Если ни одна статья не достигла порога, берем просто топ-3
    if not filtered_articles:
        filtered_articles = top_articles[:3]
    
    contexts = []
    used_ids = []
    
    for art in filtered_articles:
        file_name = art.file_name
        item_number = art.item_number
        section = art.section
        subsection = art.subsection
        
        rag_data_list = find_rag_context(file_name, item_number, section, subsection)
        for rag_data in rag_data_list:
            contexts.append(f"--- RAG Контекст ({file_name}, статья/пункт {item_number}) ---\n{rag_data['context']}")
            used_ids.append(rag_data['id'])
            
    combined_context = "\n\n".join(contexts) if contexts else ""
    return combined_context, used_ids

async def get_expert_analysis(question: str, combined_context: str, style: str = "telegram_yur", max_length: int = 4000) -> Step2Result:
    """Шаг 2: Получаем экспертный ответ на основе подготовленного контекста."""
    model_name = "gemini-3.1-pro-preview"
    model = genai.GenerativeModel(model_name)
    
    if not combined_context:
        return Step2Result(answer="К сожалению, не удалось найти детальный юридический контекст для выбранных статей.")
        
    prompt = PromptManager.get_step2_prompt(question, combined_context, style, max_length)
    
    try:
        response = await model.generate_content_async(prompt)
        usage = response.usage_metadata
        return Step2Result(
            answer=response.text,
            usage=usage,
            in_tokens=usage.prompt_token_count,
            out_tokens=usage.candidates_token_count,
            prompt=prompt
        )
    except Exception as e:
        print(f"Error in get_expert_analysis: {e}")
        return Step2Result(answer=f"Ошибка при генерации ответа: {e}", error=str(e))

async def generate_audio_script(expert_answer: str, duration: int, wpm: int = 150) -> Step3Result:
    """Шаг 3: Превращаем экспертный ответ в короткий текст для аудио."""
    model_name = "gemini-3.1-pro-preview"
    model = genai.GenerativeModel(model_name)
    
    if not expert_answer:
        return Step3Result(script="Нет текста для обработки.")
        
    # ElevenLabs speed parameter has a strict range [0.7, 1.2]. 
    # To respect duration, we must ask Gemini to generate exactly the number of words 
    # that ElevenLabs can actually read at that speed in the given duration.
    # Base effective speaking rate with tags and pauses is ~130 words per minute.
    clamped_speed = max(0.7, min(wpm / 150.0, 1.2))
    target_effective_wpm = 130.0 * clamped_speed
    
    words_per_second = target_effective_wpm / 60.0
    min_words = int(duration * words_per_second * 0.85)
    max_words = int(duration * words_per_second * 1.0)
    
    prompt = PromptManager.get_audio_script_prompt(expert_answer, duration, min_words, max_words)
    
    try:
        response = await model.generate_content_async(prompt)
        usage = response.usage_metadata
        return Step3Result(
            script=response.text,
            usage=usage,
            in_tokens=usage.prompt_token_count,
            out_tokens=usage.candidates_token_count,
            prompt=prompt
        )
    except Exception as e:
        print(f"Error in generate_audio_script: {e}")
        return Step3Result(script=f"Ошибка при генерации аудио сценария: {e}", error=str(e))

async def evaluate_audio_quality(audio_path: str, text: str, params: dict) -> dict:
    """Оценка качества аудио через Gemini 3.1 Pro Preview."""
    model_name = "gemini-3.1-pro-preview"
    model = genai.GenerativeModel(model_name)
    
    prompt = PromptManager.get_audio_evaluation_prompt(text, params)

    import asyncio
    loop = asyncio.get_event_loop()
    try:
        # Загружаем файл
        uploaded_file = await loop.run_in_executor(None, genai.upload_file, audio_path)
        
        response = await model.generate_content_async(
            [prompt, uploaded_file],
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.2,
            )
        )
        
        usage = response.usage_metadata
        in_cost, out_cost = calculate_cost(usage.prompt_token_count, usage.candidates_token_count, model_name)
        total_cost = in_cost + out_cost
        
        raw_response = re.sub(r'^```json\s*', '', response.text.strip())
        raw_response = re.sub(r'\s*```$', '', raw_response)
        data = json.loads(raw_response)
        
        # Защита от случая, когда ИИ вернул список вместо объекта
        if isinstance(data, list):
            if len(data) > 0:
                data = data[0]
            else:
                data = {}
                
        data['cost'] = total_cost
        
        # Удаляем файл из Gemini
        await loop.run_in_executor(None, genai.delete_file, uploaded_file.name)
        
        return data
    except Exception as e:
        print(f"Error in evaluate_audio_quality: {e}")
        return {"error": str(e)}
