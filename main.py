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

        # === الحل الجذري: البحث التلقائي عن الموديل المسموح لمفتاحك ===
        valid_model_name = None
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                valid_model_name = m.name.replace('models/', '')
                # التقاط أي موديل حديث متاح
                if 'gemini-1.5' in valid_model_name or 'gemini-1.0' in valid_model_name:
                    break 
        
        if not valid_model_name:
            return {"status": "error", "message": "مفتاحك لا يملك صلاحية الوصول لأي موديل توليد نصوص."}

        model = genai.GenerativeModel(valid_model_name)
        # ==============================================================

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
        ai_response = model.generate_content(prompt)

        return {
            "status": "success",
            "used_model": valid_model_name, # سيطبع لك هنا اسم الموديل الذي نجح أخيراً
            "ai_content": ai_response.text
        }

    except Exception as e:
        return {"status": "error", "message": f"الخطأ بالتفصيل: {str(e)}"}
