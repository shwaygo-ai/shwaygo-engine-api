import os
import json
import requests
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class ScrapeRequest(BaseModel):
    url: str

@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    try:
        gemini_key = os.environ.get("GEMINI_API_KEY")
        zenrows_key = os.environ.get("ZENROWS_API_KEY")

        # سحب البيانات
        zenrows_params = {"apikey": zenrows_key, "url": request.url, "js_render": "true"}
        response = requests.get("https://api.zenrows.com/v1/", params=zenrows_params)
        
        # التعديل: طلب قائمة صور
        prompt = f"""
        أنت خبير تجارة إلكترونية. حلل البيانات التالية واستخرج المعلومات بدقة.
        مهم جداً: في خانة 'images' استخرج جميع الروابط الموجودة لصور المنتج وضعها في قائمة (List).
        أجب فقط بـ JSON بالتنسيق التالي:
        {{"name": "", "images": [], "videos": [], "description": "", "features": [], "specifications": {{}}, "seo_assets": {{}}, "faq_assets": [], "reviews_assets": [], "rating": "", "back_reviews": ""}}
        البيانات الخام: {response.text[:15000]}
        """

        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        gemini_response = requests.post(gemini_url, headers=headers, json=payload)
        
        # معالجة النتيجة
        ai_text = gemini_response.json()["candidates"][0]["content"]["parts"][0]["text"]
        ai_text = ai_text.replace("```json", "").replace("
```", "").strip()
        
        data = json.loads(ai_text)
        return {"status": "success", "data": data}

    except Exception as e:
        return {"status": "error", "message": str(e)}
