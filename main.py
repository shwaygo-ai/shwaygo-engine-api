from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI()

# إعداد الـ CORS للسماح بالاتصال من أي مكان (بما في ذلك FlutterFlow)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# تعريف الهيكل الذي يستقبله السيرفر من FlutterFlow
class ScrapeRequest(BaseModel):
    url: str

# الـ Endpoint الخاص بالـ Scrape
@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    # هذه البيانات التجريبية ستظهر في FlutterFlow عند الضغط على Test
    return {
        "status": "success",
        "url": request.url,
        "current_percentage": "90%",
        "product_rating": 4.8,
        "description": "هذا وصف تجريبي من محرك ShwayGo",
        "names": "اسم المنتج التجريبي هنا",
        "seo_assets": "بيانات الـ SEO",
        "faq_assets": "بيانات الأسئلة الشائعة",
        "reviews_assets": "بيانات المراجعات",
        "features": "قائمة المميزات",
        "specifications": "المواصفات الفنية",
        "images": ["image1.jpg", "image2.jpg"],
        "videos": []
    }
