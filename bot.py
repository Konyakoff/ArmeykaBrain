import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile, BufferedInputFile

# Загружаем переменные окружения ДО импорта остальных модулей
load_dotenv()

from gemini_service import get_top_ids, get_expert_analysis, calculate_cost, get_model_info, prepare_expert_context
from database import init_db, log_message, get_db_path
from data_loader import GEMINI_MODELS

bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
dp = Dispatcher()

# Глобальные переменные
ADMIN_ID = str(os.getenv("ADMIN_ID", ""))
CURRENT_STYLE = "telegram_yur"
SELECTED_MODEL = "gemini-3.1-pro-preview"
SEND_PROMPTS = False
CONTEXT_THRESHOLD = 70
WAITING_FOR_THRESHOLD = False

def get_models_keyboard(user_id=None):
    if str(user_id) != ADMIN_ID:
        return ReplyKeyboardRemove()
        
    keyboard = []
    # Создаем кнопки по 2 в ряд
    row = []
    for model in GEMINI_MODELS:
        row.append(KeyboardButton(text=f"Модель: {model['model_name']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
import json

def get_styles():
    with open("styles.json", "r", encoding="utf-8") as f:
        return json.load(f)

def get_models_keyboard(user_id=None):
    if str(user_id) != ADMIN_ID:
        return ReplyKeyboardRemove()
        
    keyboard = []
    # Создаем кнопки по 2 в ряд
    row = []
    for model in GEMINI_MODELS:
        row.append(KeyboardButton(text=f"Модель: {model['model_name']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    styles_dict = get_styles()
    style_row = []
    for style in styles_dict.keys():
        style_row.append(KeyboardButton(text=f"Стиль: {style}"))
        if len(style_row) == 2:
            keyboard.append(style_row)
            style_row = []
    if style_row:
        keyboard.append(style_row)
        
    keyboard.append([
        KeyboardButton(text="Получать prompt.txt (Вкл)"),
        KeyboardButton(text="Получать prompt.txt (Выкл)")
    ])
    keyboard.append([
        KeyboardButton(text="dialogs.db"),
        KeyboardButton(text="Порог контекста %")
    ])
        
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True
    )

# Функция для разбивки длинных сообщений
async def send_long_message(message: types.Message, text: str):
    max_len = 4000
    for i in range(0, len(text), max_len):
        chunk = text[i:i+max_len]
        try:
            # Пытаемся отправить с красивым форматированием (bold, code blocks)
            await message.answer(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            # Если Gemini сгенерировал кривой Markdown, падаем в fallback (отправляем чистый текст)
            await message.answer(chunk)
    # Логируем исходящее сообщение
    log_message(message.from_user.id, message.from_user.username, "out", text)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    log_message(message.from_user.id, message.from_user.username, "in", message.text)
    
    if str(message.from_user.id) == ADMIN_ID:
        ans_text = "Здравствуйте! Я ИИ-юрист эксперт в области военного права.\nВыберите модель для анализа запроса, а затем задайте свой вопрос."
    else:
        ans_text = "Здравствуйте! Я ИИ-юрист эксперт в области военного права.\nПожалуйста, задайте свой вопрос."
        
    await message.answer(ans_text, reply_markup=get_models_keyboard(message.from_user.id))
    log_message(message.from_user.id, message.from_user.username, "out", ans_text)

@dp.message(F.text == "Получать prompt.txt (Вкл)")
async def cmd_prompts_on(message: types.Message):
    log_message(message.from_user.id, message.from_user.username, "in", message.text)
    if str(message.from_user.id) != ADMIN_ID:
        return
    global SEND_PROMPTS
    SEND_PROMPTS = True
    ans = "✅ Отправка prompt.txt ВКЛЮЧЕНА."
    await message.answer(ans, reply_markup=get_models_keyboard(message.from_user.id))
    log_message(message.from_user.id, message.from_user.username, "out", ans)

@dp.message(F.text == "Получать prompt.txt (Выкл)")
async def cmd_prompts_off(message: types.Message):
    log_message(message.from_user.id, message.from_user.username, "in", message.text)
    if str(message.from_user.id) != ADMIN_ID:
        return
    global SEND_PROMPTS
    SEND_PROMPTS = False
    ans = "❌ Отправка prompt.txt ВЫКЛЮЧЕНА."
    await message.answer(ans, reply_markup=get_models_keyboard(message.from_user.id))
    log_message(message.from_user.id, message.from_user.username, "out", ans)

@dp.message(F.text == "dialogs.db")
async def cmd_dialogs(message: types.Message):
    log_message(message.from_user.id, message.from_user.username, "in", message.text)
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    db_path = get_db_path()
    if os.path.exists(db_path):
        doc = FSInputFile(db_path)
        await message.answer_document(doc, caption="База данных диалогов")
        log_message(message.from_user.id, message.from_user.username, "out", "[База данных отправлена]")
    else:
        ans = "База данных пока пуста или не создана."
        await message.answer(ans)
        log_message(message.from_user.id, message.from_user.username, "out", ans)

@dp.message(F.text.startswith("Модель: "))
async def select_model(message: types.Message):
    log_message(message.from_user.id, message.from_user.username, "in", message.text)
    global SELECTED_MODEL
    
    model_name = message.text.replace("Модель: ", "").strip()
    model_info = get_model_info(model_name)
    
    if model_info:
        SELECTED_MODEL = model_name
        ans = f"✅ Модель успешно применена: <b>{model_name}</b>\n\n"
        ans += f"🔹 Макс. контекст на вход: {model_info['max_input_tokens']} токенов\n"
        ans += f"🔹 Макс. контекст на выход: {model_info['max_output_tokens']} токенов\n"
        ans += f"🔹 Цена 1 млн токенов (вход): ${model_info['price_per_1m_input']}\n"
        ans += f"🔹 Цена 1 млн токенов (выход): ${model_info['price_per_1m_output']}\n\n"
        ans += "Теперь вы можете задать свой юридический вопрос."
        await message.answer(ans, parse_mode=ParseMode.HTML)
    else:
        ans = "❌ Неизвестная модель."
        await message.answer(ans)
    
    log_message(message.from_user.id, message.from_user.username, "out", ans)

@dp.message(F.text.startswith("Стиль: "))
async def select_style(message: types.Message):
    log_message(message.from_user.id, message.from_user.username, "in", message.text)
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    global CURRENT_STYLE
    style_name = message.text.replace("Стиль: ", "").strip()
    
    styles_dict = get_styles()
    if style_name in styles_dict:
        CURRENT_STYLE = style_name
        ans = f"✅ Стиль успешно применен: <b>{style_name}</b>\n\nТеперь вы можете задать свой юридический вопрос."
        await message.answer(ans, parse_mode=ParseMode.HTML)
    else:
        ans = "❌ Неизвестный стиль."
        await message.answer(ans)
    
    log_message(message.from_user.id, message.from_user.username, "out", ans)

@dp.message(F.text == "Порог контекста %")
async def cmd_threshold(message: types.Message):
    log_message(message.from_user.id, message.from_user.username, "in", message.text)
    if str(message.from_user.id) != ADMIN_ID:
        return
    
    global WAITING_FOR_THRESHOLD
    WAITING_FOR_THRESHOLD = True
    ans = "Введи число в % - две цифры, начиная с которых ИИ будет подтягивать нужные статьи/пункты к контексту."
    await message.answer(ans)
    log_message(message.from_user.id, message.from_user.username, "out", ans)

@dp.message()
async def handle_user_query(message: types.Message):
    global WAITING_FOR_THRESHOLD, CONTEXT_THRESHOLD
    log_message(message.from_user.id, message.from_user.username, "in", message.text)
    
    is_admin = str(message.from_user.id) == ADMIN_ID
    
    if is_admin and WAITING_FOR_THRESHOLD:
        try:
            val = int(message.text.strip().replace('%', ''))
            if 0 <= val <= 100:
                CONTEXT_THRESHOLD = val
                WAITING_FOR_THRESHOLD = False
                ans = f"Новый порог в {val}% успешно установлен!"
                await message.answer(ans)
                log_message(message.from_user.id, message.from_user.username, "out", ans)
                return
            else:
                ans = "Пожалуйста, введите корректное число от 0 до 100."
                await message.answer(ans)
                log_message(message.from_user.id, message.from_user.username, "out", ans)
                return
        except ValueError:
            ans = "Пожалуйста, введите только число (например, 60)."
            await message.answer(ans)
            log_message(message.from_user.id, message.from_user.username, "out", ans)
            return

    question = message.text
    
    if is_admin:
        status_text = f"⏳ Анализирую вопрос с помощью модели {SELECTED_MODEL} и ищу подходящие статьи..."
    else:
        status_text = "Вопрос получен. Готовлю ответ..."
        
    status_msg = await message.answer(status_text)
    log_message(message.from_user.id, message.from_user.username, "out", status_text)
    
    typing_task = None
    if not is_admin:
        async def keep_typing():
            while True:
                try:
                    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
                    await asyncio.sleep(4)
                except asyncio.CancelledError:
                    break
                except:
                    break
        typing_task = asyncio.create_task(keep_typing())
    
    try:
        # Шаг 1: Ищем статьи (выбранная модель)
        top_articles, query_category, error_or_usage, in_tokens_1, out_tokens_1, prompt_step1 = await get_top_ids(question, SELECTED_MODEL)
        
        if not top_articles:
            if isinstance(error_or_usage, str):
                err_text = f"❌ Ошибка при поиске статей (сбой API или модель недоступна):\n{error_or_usage}"
            else:
                err_text = "❌ Модель не смогла найти подходящие статьи или вернула ответ в неверном формате.\n\n💡 *Совет:* Выбранная вами модель может быть недостаточно мощной для анализа такого объема юридического текста. Попробуйте выбрать более продвинутую модель (например, gemini-2.5-flash или gemini-3.1-pro-preview)."
                
            await status_msg.edit_text(err_text, parse_mode=ParseMode.MARKDOWN)
            log_message(message.from_user.id, message.from_user.username, "out", err_text)
            return
            
        # Подготавливаем контекст для 2-го шага и получаем использованные ID
        combined_context, used_ids = prepare_expert_context(top_articles, threshold=CONTEXT_THRESHOLD)
        
        # Формируем ответ по первому этапу
        in_cost_1, out_cost_1 = calculate_cost(in_tokens_1, out_tokens_1, SELECTED_MODEL)
        
        if is_admin:
            articles_list_str = "\n".join([f"Статья/Пункт {a['item_number']} - {a['file_name']} - {a['percent']}%" for a in top_articles])
            used_ids_str = "\n".join([f"• {uid}" for uid in used_ids]) if used_ids else "Нет данных"
            
            step1_text = f"🗂 <b>Классификация вопроса:</b> {query_category}\n\n"
            step1_text += f"✅ <b>Найденные статьи (ТОП-15):</b>\n{articles_list_str}\n\n"
            step1_text += f"🔍 <b>Взяты в работу (id объектов >= {CONTEXT_THRESHOLD}% или Топ-3):</b>\n{used_ids_str}\n\n"
            step1_text += "⏳ Формирую экспертное заключение (это займет немного времени)..."
            
            await status_msg.edit_text(step1_text, parse_mode=ParseMode.HTML)
            log_message(message.from_user.id, message.from_user.username, "out", step1_text)
        
        # Шаг 2: Получаем финальный ответ (всегда gemini-3.1-pro-preview)
        expert_answer, _, in_tokens_2, out_tokens_2, prompt_step2 = await get_expert_analysis(question, combined_context, style=CURRENT_STYLE)
        
        # Формируем итоговую статистику для второго шага
        in_cost_2, out_cost_2 = calculate_cost(in_tokens_2, out_tokens_2, "gemini-3.1-pro-preview")
        
        total_cost = in_cost_1 + out_cost_1 + in_cost_2 + out_cost_2
        
        if is_admin:
            stat_text = f"\n\n---\n*Статистика 1 этапа ({SELECTED_MODEL})*\n"
            stat_text += f"Вход: {in_tokens_1} (${in_cost_1:.3f})\n"
            stat_text += f"Выход: {out_tokens_1} (${out_cost_1:.3f})\n\n"
            stat_text += f"*Статистика 2 этапа (gemini-3.1-pro-preview)*\n"
            stat_text += f"Вход: {in_tokens_2} (${in_cost_2:.3f})\n"
            stat_text += f"Выход: {out_tokens_2} (${out_cost_2:.3f})\n---"
        else:
            stat_text = f"\n\n---\nЦена ИИ-вычислений: ${total_cost:.3f}"
        
        final_answer = expert_answer + stat_text
        
        # Отправляем ответ (внутри функции есть логирование)
        await send_long_message(message, final_answer)
        
        if SEND_PROMPTS and is_admin:
            if prompt_step1:
                file1 = BufferedInputFile(prompt_step1.encode("utf-8"), filename="prompt_step1.txt")
                await message.answer_document(file1)
            if prompt_step2:
                file2 = BufferedInputFile(prompt_step2.encode("utf-8"), filename="prompt_step2.txt")
                await message.answer_document(file2)
        
        # Удаляем промежуточное сообщение для обычных пользователей
        if not is_admin:
            try:
                await status_msg.delete()
            except:
                pass
        
    except Exception as e:
        err_msg = f"⚠️ Произошла ошибка при отправке ответа:\n{str(e)}"
        try:
            await status_msg.edit_text(err_msg)
        except:
            await message.answer(err_msg)
        log_message(message.from_user.id, message.from_user.username, "out", err_msg)
    finally:
        if typing_task:
            typing_task.cancel()

async def main():
    init_db()
    print("Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
