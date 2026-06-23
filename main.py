import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class ScrapeRequest(BaseModel):
    url: str

# === 1. مسار الفحص الذكي (المقترح من ChatGPT) ===
@app.get("/list_models")
async def list_models():
    try:
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if not gemini_key:
            return {"error": "المفتاح غير موجود"}
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_key}"
        response = requests.get(url)
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# === 2. مسار المحرك الأساسي (بانتظار معرفة اسم الموديل الصحيح) ===
@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    try:
        gemini_key = os.environ.get("GEMINI_API_KEY")
        zenrows_key = os.environ.get("ZENROWS_API_KEY")

        if not gemini_key or not zenrows_key:
            return {"status": "error", "message": "المفاتيح غير موجودة في الإعدادات"}

        # جلب البيانات من زين روس
        zenrows_params = {
            "apikey": zenrows_key,
            "url": request.url,
            "js_render": "true"
        }
        response = requests.get("https://api.zenrows.com/v1/", params=zenrows_params)
        
        if response.status_code != 200:
            return {"status": "error", "message": f"خطأ من زين روس: {response.status_code}", "details": response.text}

        prompt = f"قم باستخراج البيانات الأساسية وصغ وصفاً تسويقياً جذاباً للمنتج لتجهيزه للبيع:\n\n{response.text[:15000]}"
        
        # الرابط المباشر (سنقوم بتعديل اسم الموديل فور معرفة النتيجة)
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        gemini_response = requests.post(gemini_url, headers=headers, json=payload)
        gemini_data = gemini_response.json()
        
        if gemini_response.status_code != 200:
            return {"status": "error", "message": f"خطأ من جوجل: {gemini_response.status_code}", "google_details": gemini_data}
            
        ai_text = gemini_data["candidates"][0]["content"]["parts"][0]["text"]

        return {"status": "success", "ai_content": ai_text}

    except Exception as e:
        return {"status": "error", "message": f"خطأ غير متوقع: {str(e)}"}
