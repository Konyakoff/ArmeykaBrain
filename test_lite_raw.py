import asyncio
import os
import json
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

async def main():
    q = "Будет ли отсрочка от армии, если поступил в колледж, а затем отчислился и поступил в университет на очную форму обучения?"
    model = genai.GenerativeModel("gemini-flash-lite-latest")
    
    LAW_FILE_PATH = os.path.join("data", "1.St_1-35.5.FZ_53.rtf")
    sample_file = genai.upload_file(path=LAW_FILE_PATH, display_name="53-FZ_Law")
    
    prompt = f"""
Ты — юридический эксперт.
ЗАДАЧА:
Выбери статьи прилагаемого закона, которые с наибольшей вероятностью содержат ответ или полезную информацию для дачи ответа на поставленный вопрос.

Вопрос пользователя: "{q}"

Выведи топ-10 статей в порядке убывания релевантности в виде JSON.
Ожидаемый формат JSON:
[
  {{"article_number": "1", "percent": 95}},
  {{"article_number": "24", "percent": 80}}
]
"""
    for _ in range(3):
        try:
            response = await model.generate_content_async(
                [sample_file, prompt],
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                )
            )
            print("Raw response text:")
            print(response.text)
            break
        except Exception as e:
            print("Exception:", e)
    
    genai.delete_file(sample_file.name)

if __name__ == "__main__":
    asyncio.run(main())