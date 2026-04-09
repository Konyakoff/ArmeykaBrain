import asyncio
import os
from dotenv import load_dotenv
import aiohttp

load_dotenv()
api_key = os.getenv("ELEVENLABS_API_KEY")

async def test_elevenlabs_speed():
    url = "https://api.elevenlabs.io/v1/text-to-speech/pFZP5JQG7iQjIQuC4Bku"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key
    }
    
    data = {
        "text": "Это тестовое сообщение для проверки скорости генерации голоса. Раз, два, три, четыре, пять.",
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "speed": 1.5  # Let's try 1.5 to see if it fails or works
        }
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=headers) as response:
            print(f"Status with speed in voice_settings: {response.status}")
            if response.status != 200:
                print(await response.text())

    data2 = {
        "text": "Это тестовое сообщение для проверки скорости генерации голоса. Раз, два, три, четыре, пять.",
        "model_id": "eleven_multilingual_v2",
        "speed": 1.5,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
        }
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data2, headers=headers) as response:
            print(f"Status with speed at root: {response.status}")
            if response.status != 200:
                print(await response.text())

if __name__ == "__main__":
    asyncio.run(test_elevenlabs_speed())
