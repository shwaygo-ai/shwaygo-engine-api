from fastapi import FastAPI
from pydantic import BaseModel
from zenrows import ZenRowsClient
import google.generativeai as genai
import os

app = FastAPI()

# إعداد مفتاح Gemini من متغيرات البيئة
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

class ScrapeRequest(BaseModel):
    url: str

@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    # إعداد عميل ZenRows
    client = ZenRowsClient("c5c1fb32689738572ecce5fbfed1bc58f43e5954")
    url = request.url
    
    # جلب محتوى الصفحة
    response = client.get(url)
    
    # معالجة البيانات (بافتراض وجود دالة process_html في ملفك)
    product_data = process_html(response.text)
    
    # توليد المحتوى باستخدام Gemini
    model = genai.GenerativeModel('gemini-pro')
    ai_response = model.generate_content(f"قم بكتابة وصف تسويقي لهذا المنتج: {product_data}")
    ai_content = ai_response.text
    
    return {
        "status": "success",
        "url": url,
        "product_info": product_data,
        "ai_content": ai_content,
        "content_length": len(response.text)
    }
