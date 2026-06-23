import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import google.generativeai as genai
from zenrows import ZenRowsClient

app = FastAPI()

# تعريف الهيكل
class ScrapeRequest(BaseModel):
    url: str

@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    try:
        # 1. إعداد المفاتيح
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return {"status": "error", "message": "GEMINI_API_KEY not found"}
        
        genai.configure(api_key=api_key)
        
        # 2. طباعة النماذج المتاحة للـ Logs (لكي نعرف ما الذي يراه السيرفر)
        print("--- جاري فحص النماذج المتاحة ---")
        models = list(genai.list_models())
        for m in models:
            print(f"Model: {m.name}")
        print("--- نهاية القائمة ---")

        # 3. محاولة اختيار نموذج من القائمة المتاحة (سنجرب gemini-1.5-flash)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # 4. جلب البيانات (ZenRows)
        client = ZenRowsClient(os.getenv("ZENROWS_API_KEY"))
        response = client.get(request.url)
        
        # 5. التوليد بالذكاء الاصطناعي
        ai_response = model.generate_content(f"Analyze this content: {response.text[:5000]}")
        
        return {
            "status": "success",
            "ai_content": ai_response.text
        }
        
    except Exception as e:
        print(f"خطأ أثناء التنفيذ: {str(e)}")
        return {"status": "error", "details": str(e)}
