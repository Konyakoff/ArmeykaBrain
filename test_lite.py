import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from gemini_service import get_top_ids

async def main():
    q = "Будет ли отсрочка от армии, если поступил в колледж, а затем отчислился и поступил в университет на очную форму обучения?"
    print("Testing gemini-flash-lite-latest...")
    try:
        top, usage, i, o = await get_top_ids(q, "gemini-flash-lite-latest")
        print("Result:", top)
        print("Usage:", usage)
    except Exception as e:
        print("Outer error:", e)

if __name__ == "__main__":
    asyncio.run(main())