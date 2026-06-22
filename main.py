import os
from zenrows import ZenRowsClient
from fastapi import FastAPI

app = FastAPI()

# هذا السطر سيقرأ المفتاح الذي وضعناه في Render تلقائياً
client = ZenRowsClient(os.getenv("ZENROWS_API_KEY"))

@app.post("/scrape")
async def scrape_product(url: str):
    # إعدادات متقدمة لتجاوز الحظر
    params = {
        "js_render": "true",
        "antibot": "true",
        "premium_proxy": "true"
    }
    
    # تنفيذ الطلب للموقع
    response = client.get(url, params)
    
    # إرجاع المحتوى الذي سحبه ZenRows
    return {"content": response.text}
