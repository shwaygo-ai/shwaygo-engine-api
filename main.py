import os
from fastapi import FastAPI
from pydantic import BaseModel
import google.generativeai as genai
from zenrows import ZenRowsClient

# إعداد التطبيق
app = FastAPI()

# إعداد العملاء (Client Configuration)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
zenrows_client = ZenRowsClient(os.getenv("ZENROWS_API_KEY"))

# تعريف نموذج الذكاء الاصطناعي (باستخدام النموذج الموثوق من القائمة)
model = genai.GenerativeModel('models/gemini-3.5-flash')

class ScrapeRequest(BaseModel):
    url: str

@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    try:
        # 1. جلب محتوى الصفحة باستخدام ZenRows
        response = zenrows_client.get(request.url)
        
        # 2. إرسال المحتوى للذكاء الاصطناعي
        # قمنا باختصار المحتوى لتجنب مشاكل الطول الزائد
        prompt = f"Analyze this product content and provide a marketing description: {response.text[:10000]}"
        ai_response = model.generate_content(prompt)
        
        return {
            "status": "success",
            "url": request.url,
            "ai_content": ai_response.text
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
