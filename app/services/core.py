import asyncio
import logging
import time
from app.services.gemini_service import get_top_ids, get_expert_analysis, generate_audio_script, calculate_cost, get_model_info, prepare_expert_context
from app.services.claude_service import (
    get_top_ids_claude, get_expert_analysis_claude,
    generate_audio_script_claude, calculate_claude_cost
)
from app.services.elevenlabs_service import generate_audio, get_elevenlabs_voices
from app.db.database import save_result, reserve_slug, finalize_result

logger = logging.getLogger("core")


def _is_claude(model: str) -> bool:
    return model.startswith("claude-")


async def _run_with_heartbeat(coro, queue: asyncio.Queue, step_label: str, interval: int = 5):
    """
    Запускает coroutine, параллельно отправляя в очередь периодические сообщения
    типа "{step_label} (12с)..." — это позволяет фронтенду видеть, что генерация идёт,
    и принудительно флашит буферы Cloudflare/Nginx (т.к. это data:-события, а не пинги).
    """
    task = asyncio.create_task(coro)
    start = time.time()
    counter = 0
    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=interval)
            break
        except asyncio.TimeoutError:
            counter += 1
            elapsed = int(time.time() - start)
            await queue.put({
                "step": "heartbeat",
                "message": f"{step_label} (прошло {elapsed}с)...",
            })
    return await task


async def _poll_heygen_video_background(
    video_id: str, slug: str,
    avatar_id: str = "", avatar_style: str = "normal",
    video_format: str = "16:9", heygen_engine: str = "avatar_iv",
    video_stats: dict = None
):
    """
    Фоновый полинг статуса HeyGen видео (до 30 минут).
    Когда видео готово — записывает URL в saved_results и создаёт video-узел в дереве.
    Не требует открытого браузера.
    """
    from app.services.heygen_service import check_video_status
    from app.db.database import update_result_with_video_status, upsert_video_result_node

    logger.info(f"[heygen_bg] Запущен фоновый полинг video_id={video_id} slug={slug}")
    stats = video_stats or {}

    for attempt in range(180):          # 180 × 10 сек = 30 минут
        await asyncio.sleep(10)
        try:
            status_info = await check_video_status(video_id)
            if status_info["status"] == "completed" and status_info.get("video_url"):
                video_url = status_info["video_url"]
                gen_time = (attempt + 1) * 10
                stats.update({"status": "completed", "generation_time_sec": gen_time})
                update_result_with_video_status(slug, video_url)
                upsert_video_result_node(
                    slug=slug,
                    video_url=video_url,
                    video_stats=stats,
                    video_format=video_format,
                    avatar_style=avatar_style,
                    avatar_id=avatar_id,
                    heygen_engine=heygen_engine,
                )
                logger.info(f"[heygen_bg] video_id={video_id} slug={slug} готово за {gen_time}s")
                return
            elif status_info["status"] == "failed":
                error = status_info.get("error") or "неизвестная ошибка"
                logger.error(f"[heygen_bg] video_id={video_id} slug={slug} ошибка: {error}")
                return
            if attempt % 6 == 5:
                logger.info(f"[heygen_bg] video_id={video_id} slug={slug} статус={status_info['status']}, попытка {attempt+1}/180")
        except Exception as e:
            logger.error(f"[heygen_bg] video_id={video_id} slug={slug} исключение: {e}")

    logger.error(f"[heygen_bg] video_id={video_id} slug={slug} превышено время ожидания 30 мин")


async def _deepgram_background_for_slug(slug: str, audio_url_orig: str, dg_func, update_func):
    """
    Фоновая задача: запускает Deepgram для main-pipeline аудио,
    сохраняет timecodes_json_url / timecodes_vtt_url в step4_stats saved_result.
    """
    try:
        result = await dg_func(audio_url_orig)
        update_func(slug, result["json_url"], result["vtt_url"], result["cost"])
        logger.info(f"[deepgram_bg] slug={slug} таймкоды готовы: {result['json_url']}")
    except Exception as e:
        logger.error(f"[deepgram_bg] slug={slug} ошибка: {e}")

async def process_query_logic(queue: asyncio.Queue, slug: str, question: str, model: str, style: str, context_threshold: int, send_prompts: bool, max_length: int = 4000, tab_type: str = "text", audio_duration: int = 60, elevenlabs_model: str = "eleven_v3", audio_wpm: int = 150, elevenlabs_voice: str = "FGY2WhTYpPnroxEErjIq", audio_style: float = 0.25, use_speaker_boost: bool = True, audio_stability: float = 0.5, audio_similarity_boost: float = 0.75, heygen_avatar_id: str = "Abigail_standing_office_front", video_format: str = "16:9", heygen_engine: str = "avatar_iv", avatar_style: str = "auto", custom_prompts: dict = None, audio_prompt_name: str = None, model1: str = None, model2: str = None, model3: str = None):
    """
    Основная логика обработки запроса к ИИ.
    Выполняется в фоне и пишет промежуточные шаги в queue.
    """
    try:
        # Per-step models: fallback to shared `model` if not specified
        step1_model = model1 or model
        step2_model = model2 or model
        step3_model = model3 or model

        # Padding в первом событии нужен для пробивки Cloudflare/прокси-буферов (~8KB).
        # Иначе мелкое первое событие (~200 байт) удерживается до накопления буфера.
        await queue.put({
            "step": 1,
            "message": "Шаг 1: Ищем подходящие статьи и анализируем запрос...",
            "slug": slug,
            "url": f"/text/{slug}",
            "_pad": "x" * 8192,
        })
        start_time_1 = time.time()
        if _is_claude(step1_model):
            step1 = await _run_with_heartbeat(
                get_top_ids_claude(question, step1_model), queue,
                "Шаг 1: Анализирую запрос (Claude)"
            )
        else:
            step1 = await _run_with_heartbeat(
                get_top_ids(question, step1_model), queue,
                "Шаг 1: Анализирую запрос (Gemini)"
            )
        gen_time_1 = int(time.time() - start_time_1)
        
        if not step1.articles:
            if step1.error:
                err_text = f"❌ Ошибка при поиске статей (сбой API или модель недоступна):\n{step1.error}"
            else:
                err_text = "❌ Модель не смогла найти подходящие статьи или вернула ответ в неверном формате."
            
            await queue.put({"step": "error", "message": err_text})
            return
            
        combined_context, used_ids = prepare_expert_context(step1.articles, threshold=context_threshold)
        if _is_claude(step1_model):
            in_cost_1, out_cost_1 = calculate_claude_cost(step1.in_tokens, step1.out_tokens, step1_model)
        else:
            in_cost_1, out_cost_1 = calculate_cost(step1.in_tokens, step1.out_tokens, step1_model)
        
        step1_data = {
            "query_category": step1.query_category,
            "articles": [{"file_name": a.file_name, "item_number": a.item_number, "percent": a.percent} for a in step1.articles],
            "used_ids": used_ids if used_ids else []
        }
        
        step1_text = f"🗂 **Классификация вопроса:** {step1.query_category}\n\n"
        step1_text += f"✅ **Найденные статьи (ТОП-15):**\n" + "\n".join([f"Статья/Пункт {a.item_number} - {a.file_name} - {a.percent}%" for a in step1.articles]) + "\n\n"
        step1_text += f"🔍 **Взяты в работу (id объектов >= {context_threshold}% или Топ-3):**\n" + ("\n".join([f"• {uid}" for uid in used_ids]) if used_ids else "Нет данных") + "\n\n"
        
        step1_stats = {
            "model": step1_model,
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
        _cp = custom_prompts or {}
        if _is_claude(step2_model):
            step2 = await _run_with_heartbeat(
                get_expert_analysis_claude(question, combined_context, style=style,
                                           max_length=max_length,
                                           override_style=_cp.get("step2_style"),
                                           model_name=step2_model),
                queue, "Шаг 2: Формирую экспертное заключение (Claude)"
            )
            in_cost_2, out_cost_2 = calculate_claude_cost(step2.in_tokens, step2.out_tokens, step2_model)
        else:
            step2 = await _run_with_heartbeat(
                get_expert_analysis(question, combined_context, style=style,
                                    max_length=max_length,
                                    override_style=_cp.get("step2_style")),
                queue, "Шаг 2: Формирую экспертное заключение (Gemini)"
            )
            in_cost_2, out_cost_2 = calculate_cost(step2.in_tokens, step2.out_tokens, step2_model)
        gen_time_2 = int(time.time() - start_time_2)
        
        total_cost = in_cost_1 + out_cost_1 + in_cost_2 + out_cost_2
        
        step2_stats = {
            "model": step2_model,
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
            if _is_claude(step3_model):
                step3 = await _run_with_heartbeat(
                    generate_audio_script_claude(step2.answer, audio_duration, audio_wpm,
                                                 override=_cp.get("step3"), model_name=step3_model),
                    queue, "Шаг 3: Пишу аудиосценарий (Claude)"
                )
            else:
                step3 = await _run_with_heartbeat(
                    generate_audio_script(step2.answer, audio_duration, audio_wpm,
                                          override=_cp.get("step3")),
                    queue, "Шаг 3: Пишу аудиосценарий (Gemini)"
                )
            gen_time_3 = int(time.time() - start_time_3)
            
            if _is_claude(step3_model):
                in_cost_3, out_cost_3 = calculate_claude_cost(step3.in_tokens, step3.out_tokens, step3_model)
            else:
                in_cost_3, out_cost_3 = calculate_cost(step3.in_tokens, step3.out_tokens, step3_model)
            total_cost += in_cost_3 + out_cost_3
            
            step3_stats = {
                "model": step3_model,
                "in_tokens": step3.in_tokens,
                "out_tokens": step3.out_tokens,
                "in_cost": in_cost_3,
                "out_cost": out_cost_3,
                "total_cost": in_cost_3 + out_cost_3,
                "generation_time_sec": gen_time_3,
                "prompt_name": audio_prompt_name or (_cp.get("step3_name") if _cp else None) or "default",
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
                step4_audio_url_web, step4_audio_url_orig, actual_duration_sec = await _run_with_heartbeat(
                    generate_audio(step3_audio_result, elevenlabs_model, voice_id=elevenlabs_voice,
                                   speed=speed, stability=stability, similarity_boost=similarity_boost,
                                   style=audio_style, use_speaker_boost=use_speaker_boost),
                    queue, "Шаг 4: Синтезирую голос в ElevenLabs"
                )
                gen_time_4 = int(time.time() - start_time_4)
                
                # Использовать реальную длину аудио, если она доступна
                if actual_duration_sec > 0:
                    audio_duration = actual_duration_sec
                
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

                # Запускаем Deepgram таймкоды фоном сразу после генерации аудио
                if step4_audio_url_orig:
                    from app.services.deepgram_service import generate_timecodes as _dg_timecodes
                    from app.db.database import update_result_with_timecodes as _update_timecodes
                    asyncio.create_task(_deepgram_background_for_slug(
                        slug, step4_audio_url_orig, _dg_timecodes, _update_timecodes
                    ))
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
        # slug уже зарезервирован в начале — обновляем запись финальными данными
        finalize_result(
            slug,
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
            step5_video_url=None,
            step5_video_id=step5_video_id,
            step5_stats=json.dumps(step5_stats, ensure_ascii=False) if step5_stats else None,
            total_stats=json.dumps(total_stats_dict, ensure_ascii=False)
        )

        # Запускаем фоновый серверный полинг HeyGen — браузер можно закрыть
        if step5_video_id and slug:
            asyncio.create_task(_poll_heygen_video_background(
                video_id=step5_video_id, slug=slug,
                avatar_id=heygen_avatar_id, avatar_style=avatar_style,
                video_format=video_format, heygen_engine=heygen_engine,
                video_stats=dict(step5_stats) if step5_stats else {},
            ))
        
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
            step4_audio_url_web, step4_audio_url_orig, actual_duration_sec = await generate_audio(
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
            
            # Использовать реальную длину аудио, если она доступна
            if actual_duration_sec > 0:
                audio_duration = actual_duration_sec
            
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

            # Запускаем Deepgram таймкоды фоном сразу после генерации аудио
            if step4_audio_url_orig:
                from app.services.deepgram_service import generate_timecodes as _dg_timecodes
                from app.db.database import update_result_with_timecodes as _update_timecodes
                asyncio.create_task(_deepgram_background_for_slug(
                    slug, step4_audio_url_orig, _dg_timecodes, _update_timecodes
                ))
            
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
            # Фоновый серверный полинг — браузер можно закрыть
            asyncio.create_task(_poll_heygen_video_background(
                video_id=step5_video_id, slug=slug,
                avatar_id=heygen_avatar_id, avatar_style=avatar_style,
                video_format=video_format, heygen_engine=heygen_engine,
                video_stats=dict(step5_stats) if step5_stats else {},
            ))
        
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