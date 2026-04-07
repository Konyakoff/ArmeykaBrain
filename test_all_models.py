import google.generativeai as genai
import os
import json
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

available_models = []

for m in genai.list_models():
    if "generateContent" in m.supported_generation_methods:
        model_name = m.name.replace("models/", "")
        print(f"Testing {model_name}...")
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content("Hi", generation_config={"max_output_tokens": 10})
            
            # If it didn't throw an API error like 404 or 400, it's available
            # Even if response.text fails due to finish_reason=2, the model itself is accessible.
            
            available_models.append({
                "model_name": model_name,
                "max_input_tokens": m.input_token_limit,
                "max_output_tokens": m.output_token_limit,
                "price_per_1m_input": 0.0,
                "price_per_1m_output": 0.0
            })
            print(f"✅ {model_name} works!")
        except Exception as e:
            if "404" in str(e) or "400" in str(e) or "500" in str(e):
                print(f"❌ {model_name} failed: {e}")
            else:
                # Other exceptions (like ValueError for .text) mean API call succeeded but parsing failed.
                available_models.append({
                    "model_name": model_name,
                    "max_input_tokens": m.input_token_limit,
                    "max_output_tokens": m.output_token_limit,
                    "price_per_1m_input": 0.0,
                    "price_per_1m_output": 0.0
                })
                print(f"✅ {model_name} works (with parsing exception: {e})")

with open("data/gemini_models.json", "w", encoding="utf-8") as f:
    json.dump(available_models, f, indent=2, ensure_ascii=False)
