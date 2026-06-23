import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import google.generativeai as genai

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

        genai.configure(api_key=gemini_key)

        # === 1. جلب البيانات من علي إكسبريس عبر زين روس ===
        zenrows_params = {
            "apikey": zenrows_key,
            "url": request.url,
            "js_render": "true"
        }
        
        response = requests.get("https://api.zenrows.com/v1/", params=zenrows_params)
        
        if response.status_code != 200:
            return {
                "status": "error",
                "message": f"خطأ {response.status_code} من زين روس",
                "url_received": request.url,
                "zenrows_details": response.text
            }

        prompt = f"قم باستخراج البيانات الأساسية (الاسم، السعر، المواصفات) من هذا النص، وصغ وصفاً تسويقياً جذاباً: {response.text[:20000]}"
        
        # === 2. الحل الفولاذي: محرك تجربة الموديلات بالترتيب ===
        models_to_try = [
            'gemini-1.5-flash',
            'gemini-1.5-pro',
            'gemini-1.0-pro',
            'gemini-pro'
        ]
        
        ai_text = None
        used_model = None
        last_error = ""

        for model_name in models_to_try:
            try:
                # نجرب الموديل
                model = genai.GenerativeModel(model_name)
                ai_response = model.generate_content(prompt)
                
                # إذا نجح، نحفظ النتيجة ونوقف البحث فوراً
                ai_text = ai_response.text
                used_model = model_name
                break 
            except Exception as e:
                # إذا فشل الموديل، نحفظ الخطأ ونجرب الموديل الذي يليه بصمت
                last_error = str(e)
                continue 
        
        # إذا جرب كل المشتتات وفشلت كلها (وهذا مستبعد جداً)
        if not ai_text:
            return {"status": "error", "message": f"فشلت جميع الموديلات. الخطأ الأخير: {last_error}"}

        # === 3. إرجاع النتيجة النهائية لفلاتر فلو ===
        return {
            "status": "success",
            "used_model": used_model, # سيعرض لك اسم الموديل الذي نجح في المهمة
            "ai_content": ai_text
        }

    except Exception as e:
        return {"status": "error", "message": f"خطأ غير متوقع: {str(e)}"}
