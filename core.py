import asyncio
import logging
from gemini_service import get_top_ids, get_expert_analysis, generate_audio_script, calculate_cost, get_model_info, prepare_expert_context
from elevenlabs_service import generate_audio
from database import save_result

logger = logging.getLogger("core")

async def process_query_stream(question: str, model: str, style: str, context_threshold: int, send_prompts: bool, max_length: int = 4000, tab_type: str = "text", audio_duration: int = 60, elevenlabs_model: str = "eleven_multilingual_v2", audio_wpm: int = 150, elevenlabs_voice: str = "pFZP5JQG7iQjIQuC4Bku"):
    """
    Основная логика обработки запроса к ИИ с генератором состояний (Streaming).
    """
    try:
        yield {"step": 1, "message": "Шаг 1: Ищем подходящие статьи и анализируем запрос..."}
        top_articles, query_category, error_or_usage, in_tokens_1, out_tokens_1, prompt_step1 = await get_top_ids(question, model)
        
        if not top_articles:
            if isinstance(error_or_usage, str):
                err_text = f"❌ Ошибка при поиске статей (сбой API или модель недоступна):\n{error_or_usage}"
            else:
                err_text = "❌ Модель не смогла найти подходящие статьи или вернула ответ в неверном формате."
            
            yield {"step": "error", "message": err_text}
            return
            
        combined_context, used_ids = prepare_expert_context(top_articles, threshold=context_threshold)
        in_cost_1, out_cost_1 = calculate_cost(in_tokens_1, out_tokens_1, model)
        
        articles_list_str = "\n".join([f"Статья/Пункт {a['item_number']} - {a['file_name']} - {a['percent']}%" for a in top_articles])
        used_ids_str = "\n".join([f"• {uid}" for uid in used_ids]) if used_ids else "Нет данных"
        
        step1_text = f"🗂 **Классификация вопроса:** {query_category}\n\n"
        step1_text += f"✅ **Найденные статьи (ТОП-15):**\n{articles_list_str}\n\n"
        step1_text += f"🔍 **Взяты в работу (id объектов >= {context_threshold}% или Топ-3):**\n{used_ids_str}\n\n"
        
        yield {"step": "partial", "data": {"step1_info": step1_text}}
        
        yield {"step": 2, "message": "Шаг 2: Формируем экспертное заключение..."}
        expert_answer, _, in_tokens_2, out_tokens_2, prompt_step2 = await get_expert_analysis(question, combined_context, style=style, max_length=max_length)
        
        in_cost_2, out_cost_2 = calculate_cost(in_tokens_2, out_tokens_2, "gemini-3.1-pro-preview")
        total_cost = in_cost_1 + out_cost_1 + in_cost_2 + out_cost_2
        
        stat_text = f"\n\n---\n*Статистика 1 этапа ({model})*\n"
        stat_text += f"Вход: {in_tokens_1} (${in_cost_1:.3f})\n"
        stat_text += f"Выход: {out_tokens_1} (${out_cost_1:.3f})\n\n"
        stat_text += f"*Статистика 2 этапа (gemini-3.1-pro-preview)*\n"
        stat_text += f"Вход: {in_tokens_2} (${in_cost_2:.3f})\n"
        stat_text += f"Выход: {out_tokens_2} (${out_cost_2:.3f})\n"
        
        yield {"step": "partial", "data": {"answer": expert_answer}}
        
        step3_audio_result = None
        step4_audio_url = None
        prompt_step3 = None
        
        if tab_type == "audio":
            yield {"step": 3, "message": f"Шаг 3: Генерируем короткий аудиосценарий на {audio_duration} секунд..."}
            audio_script, _, in_tokens_3, out_tokens_3, prompt_step3 = await generate_audio_script(expert_answer, audio_duration, audio_wpm)
            in_cost_3, out_cost_3 = calculate_cost(in_tokens_3, out_tokens_3, "gemini-3.1-pro-preview")
            total_cost += in_cost_3 + out_cost_3
            
            stat_text += f"\n*Статистика 3 этапа (генерация аудио-скрипта)*\n"
            stat_text += f"Вход: {in_tokens_3} (${in_cost_3:.3f})\n"
            stat_text += f"Выход: {out_tokens_3} (${out_cost_3:.3f})\n"
            
            step3_audio_result = audio_script
            
            yield {"step": "partial", "data": {"step3_audio": step3_audio_result}}
            
            yield {"step": 4, "message": "Шаг 4: Синтезируем голос в ElevenLabs (может занять время)..."}
            speed = audio_wpm / 150.0
            try:
                step4_audio_url = await generate_audio(step3_audio_result, elevenlabs_model, voice_id=elevenlabs_voice, speed=speed)
                
                # Подсчет стоимости ElevenLabs
                # Creator Tier: $0.30 за 1000 символов (v2, v3). Turbo/Flash: $0.15 за 1000.
                char_count = len(step3_audio_result)
                if "turbo" in elevenlabs_model or "flash" in elevenlabs_model:
                    eleven_cost = (char_count / 1000) * 0.15
                else:
                    eleven_cost = (char_count / 1000) * 0.30
                
                total_cost += eleven_cost
                
                stat_text += f"\n*Статистика 4 этапа (ElevenLabs)*\n"
                stat_text += f"Модель: {elevenlabs_model}\n"
                stat_text += f"Диктор ID: {elevenlabs_voice}\n"
                stat_text += f"Скорость: {speed:.2f} ({audio_wpm} слов/мин)\n"
                stat_text += f"Символов: {char_count} (${eleven_cost:.3f})\n"
            except Exception as e:
                logger.error(f"Ошибка генерации аудио: {e}")
                stat_text += f"\n*Статистика 4 этапа (ElevenLabs)*\n"
                stat_text += f"Ошибка: {str(e)}\n"
            
        stat_text += f"**Общая цена ИИ-вычислений: ${total_cost:.3f}**\n---"
        
        final_answer = expert_answer + stat_text
        
        yield {"step": 5, "message": "Сохраняем результаты в базу..."}
        slug = save_result(question, step1_text, final_answer, tab_type, step3_audio_result, step4_audio_url)
        
        response_data = {
            "success": True,
            "step1_info": step1_text,
            "answer": final_answer,
            "step3_audio": step3_audio_result,
            "step4_audio_url": step4_audio_url,
            "slug": slug,
            "url": f"/text/{slug}" if slug else None,
            "step4_cost": eleven_cost if 'eleven_cost' in locals() else 0.0,
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
            },
            "voice_id": elevenlabs_voice if tab_type == "audio" else None
        }
        
        if send_prompts:
            response_data["prompts"] = {
                "step1": prompt_step1,
                "step2": prompt_step2
            }
            if prompt_step3:
                response_data["prompts"]["step3"] = prompt_step3
            
        yield {"step": "done", "result": response_data}
        
    except Exception as e:
        logger.exception(f"Exception in process_query_stream for question: {question[:50]}...")
        yield {"step": "error", "message": f"⚠️ Произошла ошибка при обработке запроса:\n{str(e)}"}