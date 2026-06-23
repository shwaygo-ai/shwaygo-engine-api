import os
import json
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 1. أولاً: تعريف التطبيق (يجب أن يكون في الأعلى)
app = FastAPI()

# 2. إعدادات الأمان
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class ScrapeRequest(BaseModel):
    url: str

# 3. أخيراً: تعريف الدالة (الآن سيتعرف السيرفر على app)
@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    try:
        gemini_key = os.environ.get("GEMINI_API_KEY")
        zenrows_key = os.environ.get("ZENROWS_API_KEY")

        if not gemini_key or not zenrows_key:
            return {"status": "error", "message": "المفاتيح غير موجودة"}

        zenrows_params = {"apikey": zenrows_key, "url": request.url, "js_render": "true"}
        response = requests.get("https://api.zenrows.com/v1/", params=zenrows_params)
        
        if response.status_code != 200:
            return {"status": "error", "message": "فشل السحب"}

        prompt = f"""
        أنت محرك معالجة بيانات منتجات. مهمتك هي استخراج وتعبئة الهيكل التالي بدقة 100%. 
        إذا كانت المعلومة غير موجودة في البيانات الخام، قم بتوليدها بذكاء.
        يجب أن يكون ردك JSON فقط، لا تكتب أي مقدمة.
        
        الهيكل المطلوب:
        {{
            "name": "اسم المنتج",
            "images": ["رابط_صورة_1", "رابط_صورة_2"],
            "videos": ["رابط_فيديو"],
            "description": "وصف تسويقي احترافي",
            "features": ["ميزة 1", "ميزة 2"],
            "specifications": {{"الخامة": "...", "اللون": "..."}},
            "seo_assets": {{"meta_title": "...", "meta_description": "...", "keywords": "..."}},
            "faq_assets": [{{"question": "...", "answer": "..."}}],
            "reviews_assets": [{{"reviewer_name": "...", "rating": 5, "comment": "..."}}],
            "rating": "4.8",
            "back_reviews": "عدد المراجعات"
        }}

        بيانات المنتج الخام المتاحة: {response.text[:15000]}
        """
        
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={gemini_key}"
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        gemini_response = requests.post(gemini_url, headers=headers, json=payload)
        
        if gemini_response.status_code != 200:
            return {"status": "error", "message": "خطأ من جوجل"}

        ai_text = gemini_response.json()["candidates"][0]["content"]["parts"][0]["text"]
        ai_text = ai_text.replace("```json", "").replace("```", "").strip()
        
        data = json.loads(ai_text)
        return {"status": "success", "data": data}

    except Exception as e:
        return {"status": "error", "message": str(e)}
