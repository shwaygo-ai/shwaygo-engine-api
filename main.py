from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# 1. إعداد الـ CORS للسماح لـ FlutterFlow بالاتصال
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ScrapeRequest(BaseModel):
    url: str

# 2. تعريف الـ POST Endpoint
@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    # هنا ستضع لاحقاً منطق الـ Scrape الخاص بك
    return {
        "status": "success",
        "url": request.url
    }
