import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()

from gemini_service import get_top_ids

async def main():
    q = "Будет ли отсрочка от армии, если поступил в колледж, а затем отчислился и поступил в университет на очную форму обучения?"
    print("Testing gemini-flash-lite-latest...")
    
    top, error_or_usage, i, o = await get_top_ids(q, "gemini-flash-lite-latest")
    
    print("Top:", top)
    print("Error or usage type:", type(error_or_usage))
    print("Error or usage:", error_or_usage)

if __name__ == "__main__":
    asyncio.run(main())