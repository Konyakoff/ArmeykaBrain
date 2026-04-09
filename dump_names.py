import asyncio
import os
from dotenv import load_dotenv
load_dotenv()
import aiohttp

async def fetch_all():
    api_key = os.getenv("ELEVENLABS_API_KEY")
    url = "https://api.elevenlabs.io/v1/voices"
    headers = {"Accept": "application/json", "xi-api-key": api_key}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            data = await response.json()
            voices = data.get("voices", [])
            for v in voices:
                print(v.get("name"))

asyncio.run(fetch_all())
