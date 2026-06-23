import os # هذا ضروري لقراءة المتغيرات من السيرفر
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

# هنا الكود يقرأ المفاتيح من إعدادات Render تلقائياً
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

class ScrapeRequest(BaseModel):
    url: str

@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    # قراءة مفتاح زين روس من المتغيرات أيضاً
    zenrows_key = os.environ.get("ZENROWS_API_KEY")
    zenrows_url = f"https://api.zenrows.com/v1/?apikey={zenrows_key}&url={request.url}&js_render=true"
    
    try:
        response = requests.get(zenrows_url)
        prompt = f"قم باستخراج البيانات الحقيقية (الاسم، السعر، المواصفات) من هذا النص وصغ وصفاً تسويقياً جذاباً: {response.text[:20000]}"
        ai_response = model.generate_content(prompt)
        
        return {
            "status": "success",
            "url": request.url,
            "ai_content": ai_response.text
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
