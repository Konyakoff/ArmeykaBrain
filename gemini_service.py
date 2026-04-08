import google.generativeai as genai
import json
import re
import os
import glob
from data_loader import JSON_DB, GEMINI_MODELS, find_rag_context

def get_styles():
    with open("styles.json", "r", encoding="utf-8") as f:
        return json.load(f)

def get_audio_prompts():
    try:
        with open("prompts_audio.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

# Настройка API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

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

async def get_top_ids(question: str, selected_model: str) -> tuple:
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
    
    prompt = f"""
Ты — врач и юрист, эксперт в области военного права.
ЗАДАЧА:
1. Изучи вопрос пользователя и определи его категорию:
   - "medical" (если в вопросе есть упоминание или состояния здоровья, или диагноза, или жалоб, или травм, или физиологических характеристик, либо суть вопроса сводится к "Освободят ли от армии с моим здоровьем?", "Какая категория годности?", "Берут ли в армию с таким заболеванием?").
   - "legal" (если вопрос чисто юридический: порядок призыва, отсрочки по учебе/работе, сроки, обжалование и т.д.).
   - "mixed" (смешанный вопрос).
2. Выбери топ-15 статей/пунктов из предоставленных выжимок нормативно-правовых актов, которые с наибольшей вероятностью могут содержать ответ.
ВНИМАНИЕ: Если категория "medical" или "mixed", ты ОБЯЗАН включить в топ как минимум 3 наиболее релевантные статьи именно из документа "3.PP_565_RaspBolezney".

Вопрос пользователя: "{question}"

Выведи ответ строго в виде JSON.
Имя файла должно быть строго без ".txt" в конце. 
Указывай четкий номер статьи или пункта из выжимки, а также (если есть) точное название раздела и подраздела, в которых находится этот пункт/статья.

ВАЖНОЕ ПРАВИЛО ОФОРМЛЕНИЯ НОМЕРОВ (item_number):
Номер должен содержать ТОЛЬКО цифры, точки и дефисы (например: "1", "2", "1.1", "1.2", "1-1", "1-2", "1.1-1", "1.1-2", "1.1.1").
КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать слова "Статья", "Пункт", "ст.", "п.", а также добавлять пробелы или любые буквы. Возвращай исключительно сам номер.

Ожидаемый формат JSON:
{{
  "query_category": "medical",
  "reasoning": "Вопрос содержит упоминание о состоянии здоровья, поэтому обязательно включаем статьи из Расписания болезней.",
  "top_articles": [
    {{"file_name": "3.PP_565_RaspBolezney", "section": "II. Расписание болезней", "subsection": "1. Инфекционные и паразитарные болезни", "item_number": "1", "percent": 95}},
    {{"file_name": "1.St_1-35.5.FZ_53", "section": "Раздел I. ОБЩИЕ ПОЛОЖЕНИЯ", "subsection": "", "item_number": "24", "percent": 80}}
  ]
}}

ВЫЖИМКИ:
{combined_vyzhimki}
"""
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
                top_articles.append({
                    "file_name": file_name,
                    "section": section,
                    "subsection": subsection,
                    "item_number": item_number,
                    "percent": percent
                })
                
        # --- ФОРСИРОВАНИЕ РАСПИСАНИЯ БОЛЕЗНЕЙ В ТОП ---
        if query_category in ["medical", "mixed"]:
            rasp_articles = [a for a in top_articles if "3.PP_565_RaspBolezney" in a["file_name"]]
            percents = [95, 94, 93]
            for i, a in enumerate(rasp_articles[:3]):
                a["percent"] = percents[i]
            
            # Сортируем заново, чтобы измененные статьи всплыли на самый верх
            top_articles.sort(key=lambda x: x.get("percent", 0), reverse=True)
                
        usage = response.usage_metadata
        return top_articles, query_category, usage, usage.prompt_token_count, usage.candidates_token_count, prompt
        
    except Exception as e:
        print(f"Error in get_top_ids: {e}")
        # Возвращаем ошибку в виде строки
        return [], "unknown", str(e), 0, 0, ""

def prepare_expert_context(top_articles: list, threshold: int = 70) -> tuple:
    """Подготавливает контекст для второго шага и возвращает (combined_context, used_ids)."""
    # Фильтруем статьи: берем только те, где вероятность >= threshold
    filtered_articles = [art for art in top_articles if art.get("percent", 0) >= threshold]
    
    # Если ни одна статья не достигла порога, берем просто топ-3
    if not filtered_articles:
        filtered_articles = top_articles[:3]
    
    contexts = []
    used_ids = []
    
    for art in filtered_articles:
        file_name = art["file_name"]
        item_number = art["item_number"]
        section = art.get("section", "")
        subsection = art.get("subsection", "")
        
        rag_data_list = find_rag_context(file_name, item_number, section, subsection)
        for rag_data in rag_data_list:
            contexts.append(f"--- RAG Контекст ({file_name}, статья/пункт {item_number}) ---\n{rag_data['context']}")
            used_ids.append(rag_data['id'])
            
    combined_context = "\n\n".join(contexts) if contexts else ""
    return combined_context, used_ids

async def get_expert_analysis(question: str, combined_context: str, style: str = "telegram_yur", max_length: int = 4000) -> tuple:
    """Шаг 2: Получаем экспертный ответ на основе подготовленного контекста."""
    model_name = "gemini-3.1-pro-preview"
    model = genai.GenerativeModel(model_name)
    
    if not combined_context:
        return "К сожалению, не удалось найти детальный юридический контекст для выбранных статей.", None, 0, 0
        
    styles_dict = get_styles()
    system_prompt_template = styles_dict.get(style, styles_dict.get("telegram_yur", ""))
    system_prompt = system_prompt_template.replace("{max_length}", str(max_length))
    
    prompt = f"""{system_prompt}

Вопрос пользователя: "{question}"

Юридический контекст для анализа (выдержки из НПА):
{combined_context}

Дай максимально качественный ответ на поставленный вопрос, аргументируя ответ точными цитатами из предоставленного юридического контекста. Если в контексте нет ответа на вопрос, честно скажи об этом.
"""
    try:
        response = await model.generate_content_async(prompt)
        usage = response.usage_metadata
        return response.text, usage, usage.prompt_token_count, usage.candidates_token_count, prompt
    except Exception as e:
        print(f"Error in get_expert_analysis: {e}")
        return f"Ошибка при генерации ответа: {e}", None, 0, 0, ""

async def generate_audio_script(expert_answer: str, duration: int, wpm: int = 150) -> tuple:
    """Шаг 3: Превращаем экспертный ответ в короткий текст для аудио."""
    model_name = "gemini-3.1-pro-preview"
    model = genai.GenerativeModel(model_name)
    
    if not expert_answer:
        return "Нет текста для обработки.", None, 0, 0, ""
        
    prompts_dict = get_audio_prompts()
    system_prompt_template = prompts_dict.get("default", "Произошла ошибка загрузки промпта из файла prompts_audio.json")
    
    words_per_second = wpm / 60.0
    min_words = int(duration * words_per_second * 0.9)
    max_words = int(duration * words_per_second * 1.1)
    
    prompt = system_prompt_template.replace("[ВСТАВИТЬ ВАШ ИСХОДНЫЙ ТЕКСТ]", expert_answer)
    prompt = prompt.replace("[N]", str(duration))
    prompt = prompt.replace("[N * 2]", str(min_words))
    prompt = prompt.replace("[N * 2.5]", str(max_words))
    
    try:
        response = await model.generate_content_async(prompt)
        usage = response.usage_metadata
        return response.text, usage, usage.prompt_token_count, usage.candidates_token_count, prompt
    except Exception as e:
        print(f"Error in generate_audio_script: {e}")
        return f"Ошибка при генерации аудио сценария: {e}", None, 0, 0, ""
