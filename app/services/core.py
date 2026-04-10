import asyncio
import logging
import time
from app.services.gemini_service import get_top_ids, get_expert_analysis, generate_audio_script, calculate_cost, get_model_info, prepare_expert_context
from app.services.elevenlabs_service import generate_audio, get_elevenlabs_voices
from app.db.database import save_result

logger = logging.getLogger("core")

async def process_query_logic(queue: asyncio.Queue, question: str, model: str, style: str, context_threshold: int, send_prompts: bool, max_length: int = 4000, tab_type: str = "text", audio_duration: int = 60, elevenlabs_model: str = "eleven_v3", audio_wpm: int = 150, elevenlabs_voice: str = "FGY2WhTYpPnroxEErjIq", audio_style: float = 0.25, use_speaker_boost: bool = True, audio_stability: float = 0.5, audio_similarity_boost: float = 0.75, heygen_avatar_id: str = "Abigail_standing_office_front", video_format: str = "16:9", heygen_engine: str = "avatar_iv", avatar_style: str = "auto"):
    """
    Основная логика обработки запроса к ИИ.
    Выполняется в фоне и пишет промежуточные шаги в queue.
    """
    try:
        await queue.put({"step": 1, "message": "Шаг 1: Ищем подходящие статьи и анализируем запрос..."})
        start_time_1 = time.time()
        step1 = await get_top_ids(question, model)
        gen_time_1 = int(time.time() - start_time_1)
        
        if not step1.articles:
            if step1.error:
                err_text = f"❌ Ошибка при поиске статей (сбой API или модель недоступна):\n{step1.error}"
            else:
                err_text = "❌ Модель не смогла найти подходящие статьи или вернула ответ в неверном формате."
            
            await queue.put({"step": "error", "message": err_text})
            return
            
        combined_context, used_ids = prepare_expert_context(step1.articles, threshold=context_threshold)
        in_cost_1, out_cost_1 = calculate_cost(step1.in_tokens, step1.out_tokens, model)
        
        step1_data = {
            "query_category": step1.query_category,
            "articles": [{"file_name": a.file_name, "item_number": a.item_number, "percent": a.percent} for a in step1.articles],
            "used_ids": used_ids if used_ids else []
        }
        
        step1_text = f"🗂 **Классификация вопроса:** {step1.query_category}\n\n"
        step1_text += f"✅ **Найденные статьи (ТОП-15):**\n" + "\n".join([f"Статья/Пункт {a.item_number} - {a.file_name} - {a.percent}%" for a in step1.articles]) + "\n\n"
        step1_text += f"🔍 **Взяты в работу (id объектов >= {context_threshold}% или Топ-3):**\n" + ("\n".join([f"• {uid}" for uid in used_ids]) if used_ids else "Нет данных") + "\n\n"
        
        step1_stats = {
            "model": model,
            "in_tokens": step1.in_tokens,
            "out_tokens": step1.out_tokens,
            "in_cost": in_cost_1,
            "out_cost": out_cost_1,
            "total_cost": in_cost_1 + out_cost_1,
            "generation_time_sec": gen_time_1
        }
        await queue.put({"step": "partial", "data": {"step1_info": step1_data, "step1_stats": step1_stats}})
        
        await queue.put({"step": 2, "message": "Шаг 2: Формируем экспертное заключение..."})
        start_time_2 = time.time()
        step2 = await get_expert_analysis(question, combined_context, style=style, max_length=max_length)
        gen_time_2 = int(time.time() - start_time_2)
        
        in_cost_2, out_cost_2 = calculate_cost(step2.in_tokens, step2.out_tokens, "gemini-3.1-pro-preview")
        total_cost = in_cost_1 + out_cost_1 + in_cost_2 + out_cost_2
        
        step2_stats = {
            "model": "gemini-3.1-pro-preview",
            "in_tokens": step2.in_tokens,
            "out_tokens": step2.out_tokens,
            "in_cost": in_cost_2,
            "out_cost": out_cost_2,
            "total_cost": in_cost_2 + out_cost_2,
            "generation_time_sec": gen_time_2
        }
        await queue.put({"step": "partial", "data": {"answer": step2.answer, "step2_stats": step2_stats}})
        
        step3_audio_result = None
        step4_audio_url_web = None
        step4_audio_url_orig = None
        prompt_step3 = None
        step3_stats = None
        step4_stats = None
        
        if tab_type in ["audio", "video"]:
            await queue.put({"step": 3, "message": f"Шаг 3: Генерируем короткий аудиосценарий на {audio_duration} секунд..."})
            start_time_3 = time.time()
            step3 = await generate_audio_script(step2.answer, audio_duration, audio_wpm)
            gen_time_3 = int(time.time() - start_time_3)
            
            in_cost_3, out_cost_3 = calculate_cost(step3.in_tokens, step3.out_tokens, "gemini-3.1-pro-preview")
            total_cost += in_cost_3 + out_cost_3
            
            step3_stats = {
                "model": "gemini-3.1-pro-preview",
                "in_tokens": step3.in_tokens,
                "out_tokens": step3.out_tokens,
                "in_cost": in_cost_3,
                "out_cost": out_cost_3,
                "total_cost": in_cost_3 + out_cost_3,
                "generation_time_sec": gen_time_3
            }
            
            step3_audio_result = step3.script
            prompt_step3 = step3.prompt
            
            await queue.put({"step": "partial", "data": {"step3_audio": step3_audio_result, "step3_stats": step3_stats}})
            
            await queue.put({"step": 4, "message": "Шаг 4: Синтезируем голос в ElevenLabs (может занять время)..."})
            speed = max(0.7, min(audio_wpm / 150.0, 1.2))
            stability = audio_stability
            similarity_boost = audio_similarity_boost
            
            voices = await get_elevenlabs_voices()
            voice_name = next((v['name'] for v in voices if v['voice_id'] == elevenlabs_voice), elevenlabs_voice)
            
            try:
                start_time_4 = time.time()
                step4_audio_url_web, step4_audio_url_orig = await generate_audio(step3_audio_result, elevenlabs_model, voice_id=elevenlabs_voice, speed=speed, stability=stability, similarity_boost=similarity_boost, style=audio_style, use_speaker_boost=use_speaker_boost)
                gen_time_4 = int(time.time() - start_time_4)
                
                char_count = len(step3_audio_result)
                if "turbo" in elevenlabs_model or "flash" in elevenlabs_model:
                    eleven_cost = (char_count / 1000) * 0.15
                else:
                    eleven_cost = (char_count / 1000) * 0.30
                
                total_cost += eleven_cost
                
                step4_stats = {
                    "model": elevenlabs_model,
                    "voice_id": elevenlabs_voice,
                    "voice_name": voice_name,
                    "duration_sec": audio_duration,
                    "speed": speed,
                    "wpm": audio_wpm,
                    "stability": stability,
                    "similarity": similarity_boost,
                    "style": audio_style,
                    "speaker_boost": use_speaker_boost,
                    "char_count": char_count,
                    "total_cost": eleven_cost,
                    "generation_time_sec": gen_time_4
                }
                await queue.put({"step": "partial", "data": {"step4_audio_url": step4_audio_url_web, "step4_stats": step4_stats}})
            except Exception as e:
                logger.error(f"Ошибка генерации аудио: {e}")
                step4_stats = {"error": str(e)}
        
        step5_video_id = None
        step5_video_url = None
        step5_stats = None
        if tab_type == "video" or (tab_type == "text" and locals().get("generate_video", False)):
            await queue.put({"step": 5, "message": "Шаг 5: Инициализация видео в HeyGen (может занять 3-10 минут)..."})
            from app.services.heygen_service import generate_video_from_audio, calculate_heygen_cost
            try:
                # В HeyGen отправляем полный публичный URL аудиофайла
                host_url = "https://armeykabrain.net"
                public_audio_url = step4_audio_url_orig if step4_audio_url_orig.startswith("http") else f"{host_url}{step4_audio_url_orig}"
                
                step5_video_id = await generate_video_from_audio(heygen_avatar_id, public_audio_url, title="ArmeykaBrain Video", video_format=video_format, heygen_engine=heygen_engine, avatar_style=avatar_style)
                
                step5_cost = calculate_heygen_cost(audio_duration, heygen_engine)
                total_cost += step5_cost
                
                step5_stats = {
                    "model": "heygen_v2",
                    "avatar_id": heygen_avatar_id,
                    "avatar_style": avatar_style,
                    "video_id": step5_video_id,
                    "total_cost": step5_cost,
                    "status": "pending",
                    "started_at": int(time.time())
                }
                await queue.put({"step": "partial", "data": {"step5_video_id": step5_video_id, "step5_stats": step5_stats}})
            except Exception as e:
                logger.error(f"Ошибка генерации видео HeyGen: {e}")
                step5_stats = {"error": str(e)}
                await queue.put({"step": "error", "message": f"Ошибка HeyGen: {str(e)}"})
                # Не прерываем выполнение, пусть сохранит результат с ошибкой видео
                
        total_stats_dict = {"total_cost": total_cost}
        
        final_answer = step2.answer # Мы больше не клеим stat_text
        
        import json
        await queue.put({"step": 6 if (tab_type == "video") else 5, "message": "Сохраняем результаты в базу..."})
        slug = save_result(
            question, 
            step1_text, 
            final_answer, 
            tab_type, 
            step3_audio_result, 
            step4_audio_url_web, 
            step4_audio_url_orig,
            step1_stats=json.dumps(step1_stats, ensure_ascii=False) if step1_stats else None,
            step2_stats=json.dumps(step2_stats, ensure_ascii=False) if step2_stats else None,
            step3_stats=json.dumps(step3_stats, ensure_ascii=False) if step3_stats else None,
            step4_stats=json.dumps(step4_stats, ensure_ascii=False) if step4_stats else None,
            step5_video_url=None, # Еще не готово
            step5_video_id=step5_video_id,
            step5_stats=json.dumps(step5_stats, ensure_ascii=False) if step5_stats else None,
            total_stats=json.dumps(total_stats_dict, ensure_ascii=False)
        )
        
        response_data = {
            "success": True,
            "step1_info": step1_text,
            "step1_stats": step1_stats,
            "answer": final_answer,
            "step2_stats": step2_stats,
            "step3_audio": step3_audio_result,
            "step3_stats": step3_stats,
            "step4_audio_url": step4_audio_url_web,
            "step4_audio_url_original": step4_audio_url_orig,
            "step4_stats": step4_stats,
            "step5_video_id": step5_video_id,
            "step5_stats": step5_stats,
            "total_stats": total_stats_dict,
            "slug": slug,
            "url": f"/text/{slug}" if slug else None,
            "voice_id": elevenlabs_voice if tab_type == "audio" else None
        }
        
        if send_prompts:
            response_data["prompts"] = {
                "step1": step1.prompt,
                "step2": step2.prompt
            }
            if prompt_step3:
                response_data["prompts"]["step3"] = prompt_step3
            
        await queue.put({"step": "done", "result": response_data})
        
    except Exception as e:
        logger.exception(f"Exception in process_query_logic for question: {question[:50]}...")
        await queue.put({"step": "error", "message": f"⚠️ Произошла ошибка при обработке запроса:\n{str(e)}"})

async def process_upgrade_to_audio_logic(queue: asyncio.Queue, slug: str, raw_answer: str, audio_duration: int = 60, elevenlabs_model: str = "eleven_v3", audio_wpm: int = 150, elevenlabs_voice: str = "FGY2WhTYpPnroxEErjIq", audio_style: float = 0.25, use_speaker_boost: bool = True, audio_stability: float = 0.5, audio_similarity_boost: float = 0.75, previous_total_cost: float = 0.0, generate_video: bool = False, heygen_avatar_id: str = "Abigail_standing_office_front", video_format: str = "16:9", heygen_engine: str = "avatar_iv", avatar_style: str = "auto"):
    """Логика конвертации существующего текстового результата в аудио."""
    from app.db.database import update_result_with_audio
    
    try:
        # Extract clean expert text (before "---" stats separator if exists)
        expert_answer = raw_answer.split("---")[0].strip()
        
        await queue.put({"step": 3, "message": f"Шаг 3: Генерируем короткий аудиосценарий на {audio_duration} секунд..."})
        start_time_3 = time.time()
        step3 = await generate_audio_script(expert_answer, audio_duration, audio_wpm)
        gen_time_3 = int(time.time() - start_time_3)
        
        in_cost_3, out_cost_3 = calculate_cost(step3.in_tokens, step3.out_tokens, "gemini-3.1-pro-preview")
        total_cost = previous_total_cost + in_cost_3 + out_cost_3
        
        step3_stats = {
            "model": "gemini-3.1-pro-preview",
            "in_tokens": step3.in_tokens,
            "out_tokens": step3.out_tokens,
            "in_cost": in_cost_3,
            "out_cost": out_cost_3,
            "total_cost": in_cost_3 + out_cost_3,
            "generation_time_sec": gen_time_3
        }
        
        step3_audio_result = step3.script
        await queue.put({"step": "partial", "data": {"step3_audio": step3_audio_result, "step3_stats": step3_stats}})
        
        await queue.put({"step": 4, "message": "Шаг 4: Синтезируем голос в ElevenLabs (может занять время)..."})
        speed = max(0.7, min(audio_wpm / 150.0, 1.2))
        stability = audio_stability
        similarity_boost = audio_similarity_boost
        
        voices = await get_elevenlabs_voices()
        voice_name = next((v['name'] for v in voices if v['voice_id'] == elevenlabs_voice), elevenlabs_voice)
        
        try:
            start_time_4 = time.time()
            step4_audio_url_web, step4_audio_url_orig = await generate_audio(
                step3_audio_result, 
                elevenlabs_model, 
                voice_id=elevenlabs_voice, 
                speed=speed, 
                stability=stability, 
                similarity_boost=similarity_boost, 
                style=audio_style, 
                use_speaker_boost=use_speaker_boost
            )
            gen_time_4 = int(time.time() - start_time_4)
            
            char_count = len(step3_audio_result)
            if "turbo" in elevenlabs_model or "flash" in elevenlabs_model:
                eleven_cost = (char_count / 1000) * 0.15
            else:
                eleven_cost = (char_count / 1000) * 0.30
                
            total_cost += eleven_cost
            
            step4_stats = {
                "model": elevenlabs_model,
                "voice_id": elevenlabs_voice,
                "voice_name": voice_name,
                "duration_sec": audio_duration,
                "speed": speed,
                "wpm": audio_wpm,
                "stability": stability,
                "similarity": similarity_boost,
                "style": audio_style,
                "speaker_boost": use_speaker_boost,
                "char_count": char_count,
                "total_cost": eleven_cost,
                "generation_time_sec": gen_time_4
            }
            await queue.put({"step": "partial", "data": {"step4_audio_url": step4_audio_url_web, "step4_stats": step4_stats}})
            
        except Exception as e:
            logger.error(f"Ошибка генерации аудио: {e}")
            step4_stats = {"error": str(e)}
            await queue.put({"step": "error", "message": f"Ошибка ElevenLabs: {str(e)}"})
            return

        step5_video_id = None
        step5_video_url = None
        step5_stats = None
        
        if generate_video:
            await queue.put({"step": 5, "message": "Шаг 5: Инициализация видео в HeyGen (может занять 3-10 минут)..."})
            from app.services.heygen_service import generate_video_from_audio, calculate_heygen_cost
            try:
                host_url = "https://armeykabrain.net"
                public_audio_url = step4_audio_url_orig if step4_audio_url_orig.startswith("http") else f"{host_url}{step4_audio_url_orig}"
                
                step5_video_id = await generate_video_from_audio(heygen_avatar_id, public_audio_url, title="ArmeykaBrain Video", video_format=video_format, heygen_engine=heygen_engine, avatar_style=avatar_style)
                
                step5_cost = calculate_heygen_cost(audio_duration, heygen_engine)
                total_cost += step5_cost
                
                step5_stats = {
                    "model": "heygen_v2",
                    "avatar_id": heygen_avatar_id,
                    "avatar_style": avatar_style,
                    "video_id": step5_video_id,
                    "total_cost": step5_cost,
                    "status": "pending",
                    "started_at": int(time.time())
                }
                await queue.put({"step": "partial", "data": {"step5_video_id": step5_video_id, "step5_stats": step5_stats}})
            except Exception as e:
                logger.error(f"Ошибка генерации видео HeyGen: {e}")
                step5_stats = {"error": str(e)}
                await queue.put({"step": "error", "message": f"Ошибка HeyGen: {str(e)}"})

        total_stats_dict = {"total_cost": total_cost}
        
        import json
        await queue.put({"step": 6 if generate_video else 5, "message": "Сохраняем аудио в базу данных..."})
        update_result_with_audio(
            slug, 
            step3_audio_result, 
            step4_audio_url_web, 
            step4_audio_url_orig,
            step3_stats=json.dumps(step3_stats, ensure_ascii=False),
            step4_stats=json.dumps(step4_stats, ensure_ascii=False),
            total_stats=json.dumps(total_stats_dict, ensure_ascii=False)
        )
        if generate_video and step5_video_id:
            from app.db.database import update_result_with_video
            update_result_with_video(slug, step5_video_id, json.dumps(step5_stats, ensure_ascii=False), json.dumps(total_stats_dict, ensure_ascii=False))
        
        response_data = {
            "success": True,
            "step3_audio": step3_audio_result,
            "step3_stats": step3_stats,
            "step4_audio_url": step4_audio_url_web,
            "step4_audio_url_original": step4_audio_url_orig,
            "step4_stats": step4_stats,
            "step5_video_id": step5_video_id,
            "step5_stats": step5_stats,
            "total_stats": total_stats_dict,
            "slug": slug,
            "url": f"/text/{slug}",
            "voice_id": elevenlabs_voice
        }
        
        await queue.put({"step": "done", "result": response_data})
        
    except Exception as e:
        logger.exception(f"Exception in process_upgrade_to_audio_logic for slug: {slug}")
        await queue.put({"step": "error", "message": f"⚠️ Произошла ошибка при обработке запроса:\n{str(e)}"})