from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from zenrows import ZenRowsClient

app = FastAPI()

# إعداد الـ CORS للسماح بالاتصال من FlutterFlow
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ScrapeRequest(BaseModel):
    url: str

@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    # الكي الخاص بك مدمج هنا
    client = ZenRowsClient("c5c1fb32689738572ecce5fbfed1bc58f43e7841")
    
    url = request.url
    # جلب محتوى الصفحة
    response = client.get(url)
    
    return {
        "status": "success",
        "url": url,
        "content_length": len(response.text)
    }
