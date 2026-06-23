import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import google.generativeai as genai

app = FastAPI()

# 1. بوابة الاتصال لـ FlutterFlow (لحل مشكلة Failed to fetch)
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
            return {"status": "error", "message": "المفاتيح غير موجودة في إعدادات Render"}

        # 2. استخدام النسخة الأساسية والمستقرة جداً (gemini-pro) التي تمنع ظهور خطأ 404
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel('gemini-pro')

        # 3. جلب البيانات من علي إكسبريس عبر ZenRows
        zenrows_url = f"https://api.zenrows.com/v1/?apikey={zenrows_key}&url={request.url}&js_render=true"
        response = requests.get(zenrows_url)
        
        if response.status_code != 200:
            return {"status": "error", "message": f"خطأ في الاتصال بـ ZenRows: {response.status_code}"}

        # 4. توليد المحتوى
        prompt = f"قم باستخراج البيانات الأساسية (الاسم، السعر، المواصفات) وصغ وصفاً تسويقياً جذاباً: {response.text[:20000]}"
        ai_response = model.generate_content(prompt)

        return {
            "status": "success",
            "ai_content": ai_response.text
        }

    except Exception as e:
        # صائد الأخطاء: يمنع ظهور 500 Internal Error ويعطيك الخطأ الحقيقي
        return {"status": "error", "message": f"الخطأ بالتفصيل: {str(e)}"}
