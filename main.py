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

@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    try:
        gemini_key = os.environ.get("GEMINI_API_KEY")
        zenrows_key = os.environ.get("ZENROWS_API_KEY")

        if not gemini_key or not zenrows_key:
            return {"status": "error", "message": "المفاتيح غير موجودة في الإعدادات"}

        # === 1. جلب البيانات من زين روس ===
        zenrows_params = {
            "apikey": zenrows_key,
            "url": request.url,
            "js_render": "true"
        }
        
        response = requests.get("https://api.zenrows.com/v1/", params=zenrows_params)
        
        if response.status_code != 200:
            return {
                "status": "error",
                "message": f"خطأ من زين روس: {response.status_code}",
                "details": response.text
            }

        # نجهز الأمر الذي سيقوم بتهيئة المنتج
        prompt = f"قم باستخراج البيانات الأساسية (الاسم، السعر، المواصفات) من هذا النص، وصغ وصفاً تسويقياً جذاباً للمنتج لتجهيزه للبيع:\n\n{response.text[:15000]}"
        
        # === 2. التغيير الجذري: استخدام الرابط المباشر لموديل 1.5-flash المتوافق مع مفتاحك الجديد ===
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        
        gemini_response = requests.post(gemini_url, headers=headers, json=payload)
        gemini_data = gemini_response.json()
        
        if gemini_response.status_code != 200:
            return {
                "status": "error",
                "message": f"خطأ من جوجل: {gemini_response.status_code}",
                "google_details": gemini_data 
            }
            
        ai_text = gemini_data["candidates"][0]["content"]["parts"][0]["text"]

        # === 3. إرجاع النتيجة النهائية لفلاتر فلو ===
        return {
            "status": "success",
            "ai_content": ai_text
        }

    except Exception as e:
        return {"status": "error", "message": f"خطأ غير متوقع: {str(e)}"}
