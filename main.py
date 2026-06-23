from fastapi import FastAPI
from pydantic import BaseModel
from zenrows import ZenRowsClient
import google.generativeai as genai
import os

app = FastAPI()

# إعداد مفتاح API الخاص بـ Gemini من متغيرات البيئة في Render
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# تعريف دالة المعالجة الأساسية
def process_html(html_content):
    # حالياً تعيد بيانات تجريبية لضمان عمل المسار البرمجي
    return {"product_name": "Product Detected", "price": "Check site for price"}

class ScrapeRequest(BaseModel):
    url: str

@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    # إعداد عميل ZenRows
    client = ZenRowsClient("c5c1fb32689738572ecce5fbfed1bc58f43e5954")
    url = request.url
    
    # جلب محتوى الصفحة
    response = client.get(url)
    
    # معالجة محتوى HTML
    product_data = process_html(response.text)
    
    # استخدام Gemini لتوليد المحتوى
    model = genai.GenerativeModel('gemini-pro')
    ai_response = model.generate_content(f"Write a marketing description for this product: {product_data}")
    ai_content = ai_response.text
    
    # إرجاع النتيجة النهائية
    return {
        "status": "success",
        "url": url,
        "product_info": product_data,
        "ai_content": ai_content,
        "content_length": len(response.text)
    }
