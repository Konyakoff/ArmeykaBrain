import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

async def fetch_all():
    api_key = os.getenv("ELEVENLABS_API_KEY")
    url = "https://api.elevenlabs.io/v1/voices"
    headers = {"Accept": "application/json", "xi-api-key": api_key}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            data = await response.json()
            voices = data.get("voices", [])
            tags = {"gender": set(), "age": set(), "descriptive": set(), "use_case": set()}
            for v in voices:
                labels = v.get("labels", {})
                for k in tags.keys():
                    val = labels.get(k)
                    if val:
                        tags[k].add(val.lower())
            
            for k, v in tags.items():
                print(f"{k}: {sorted(list(v))}")

asyncio.run(fetch_all())