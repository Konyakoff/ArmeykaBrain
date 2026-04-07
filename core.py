import asyncio
import logging
from gemini_service import get_top_ids, get_expert_analysis, calculate_cost, get_model_info, prepare_expert_context

logger = logging.getLogger("core")

async def process_query(question: str, model: str, style: str, context_threshold: int, send_prompts: bool, max_length: int = 4000):
    """
    Основная логика обработки запроса к ИИ.
    Возвращает словарь с результатами и статистикой.
    """
    try:
        # Шаг 1: Ищем статьи (выбранная модель)
        top_articles, query_category, error_or_usage, in_tokens_1, out_tokens_1, prompt_step1 = await get_top_ids(question, model)
        
        if not top_articles:
            if isinstance(error_or_usage, str):
                err_text = f"❌ Ошибка при поиске статей (сбой API или модель недоступна):\n{error_or_usage}"
            else:
                err_text = "❌ Модель не смогла найти подходящие статьи или вернула ответ в неверном формате.\n\n💡 *Совет:* Выбранная вами модель может быть недостаточно мощной для анализа такого объема юридического текста. Попробуйте выбрать более продвинутую модель (например, gemini-2.5-flash или gemini-3.1-pro-preview)."
            
            return {
                "success": False,
                "error": err_text
            }
            
        # Подготавливаем контекст для 2-го шага и получаем использованные ID
        combined_context, used_ids = prepare_expert_context(top_articles, threshold=context_threshold)
        
        # Формируем ответ по первому этапу
        in_cost_1, out_cost_1 = calculate_cost(in_tokens_1, out_tokens_1, model)
        
        articles_list_str = "\n".join([f"Статья/Пункт {a['item_number']} - {a['file_name']} - {a['percent']}%" for a in top_articles])
        used_ids_str = "\n".join([f"• {uid}" for uid in used_ids]) if used_ids else "Нет данных"
        
        step1_text = f"🗂 **Классификация вопроса:** {query_category}\n\n"
        step1_text += f"✅ **Найденные статьи (ТОП-15):**\n{articles_list_str}\n\n"
        step1_text += f"🔍 **Взяты в работу (id объектов >= {context_threshold}% или Топ-3):**\n{used_ids_str}\n\n"
        
        # Шаг 2: Получаем финальный ответ (всегда gemini-3.1-pro-preview)
        expert_answer, _, in_tokens_2, out_tokens_2, prompt_step2 = await get_expert_analysis(question, combined_context, style=style, max_length=max_length)
        
        # Формируем итоговую статистику для второго шага
        in_cost_2, out_cost_2 = calculate_cost(in_tokens_2, out_tokens_2, "gemini-3.1-pro-preview")
        total_cost = in_cost_1 + out_cost_1 + in_cost_2 + out_cost_2
        
        stat_text = f"\n\n---\n*Статистика 1 этапа ({model})*\n"
        stat_text += f"Вход: {in_tokens_1} (${in_cost_1:.3f})\n"
        stat_text += f"Выход: {out_tokens_1} (${out_cost_1:.3f})\n\n"
        stat_text += f"*Статистика 2 этапа (gemini-3.1-pro-preview)*\n"
        stat_text += f"Вход: {in_tokens_2} (${in_cost_2:.3f})\n"
        stat_text += f"Выход: {out_tokens_2} (${out_cost_2:.3f})\n"
        stat_text += f"**Общая цена ИИ-вычислений: ${total_cost:.3f}**\n---"
        
        final_answer = expert_answer + stat_text
        
        response_data = {
            "success": True,
            "step1_info": step1_text,
            "answer": final_answer,
            "stats": {
                "in_tokens_1": in_tokens_1,
                "out_tokens_1": out_tokens_1,
                "in_cost_1": in_cost_1,
                "out_cost_1": out_cost_1,
                "in_tokens_2": in_tokens_2,
                "out_tokens_2": out_tokens_2,
                "in_cost_2": in_cost_2,
                "out_cost_2": out_cost_2,
                "total_cost": total_cost
            }
        }
        
        if send_prompts:
            response_data["prompts"] = {
                "step1": prompt_step1,
                "step2": prompt_step2
            }
            
        return response_data
        
    except Exception as e:
        logger.exception(f"Exception in process_query for question: {question[:50]}...")
        return {
            "success": False,
            "error": f"⚠️ Произошла ошибка при обработке запроса:\n{str(e)}"
        }