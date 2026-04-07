import google.generativeai as genai
import os
import json
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

model = genai.GenerativeModel('gemini-2.5-flash')
response = model.generate_content("Hello", generation_config={"max_output_tokens": 10})
print("gemini-2.5-flash:", response.text)

model = genai.GenerativeModel('gemini-2.5-pro')
response = model.generate_content("Hello", generation_config={"max_output_tokens": 10})
print("gemini-2.5-pro:", response.text)
