import os
import json
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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

        # سحب البيانات الخام من الموقع
        zenrows_params = {"apikey": zenrows_key, "url": request.url, "js_render": "true"}
        response = requests.get("https://api.zenrows.com/v1/", params=zenrows_params)
        raw_html = response.text[:80000] # حجم مناسب لجلب كل الصور والفيديوهات

        # صياغة الأمر للدورين: الاستخراج بدقة والتأليف الاحترافي لباقي الصفحات
        prompt = f"""
        You are the core engine of 'ShwayGo' (a trending e-commerce optimization SaaS).
        Your job is split into two parts based on the raw HTML provided:

        PART 1: DIRECT EXTRACTION (The 5 Core Assets)
        1. Extract ALL available product image URLs into the 'images' array. Do not miss any.
        2. Extract ALL available product video URLs into the 'videos' array.
        3. Extract the product rating/stars into 'rating'.
        4. Extract the raw product title and raw description from the HTML to use as your context.

        PART 2: AI CREATION & MARKETING AUTHORING (The Remaining Pages)
        Based ONLY on the extracted raw title and description, you must CRAFT and GENERATE high-converting, trending marketing content for the other fields:
        1. 'name': Write an optimized, catchy, trending product title.
        2. 'description': Write a highly persuasive, emotional, and conversion-focused marketing description (do NOT just copy the raw text, enhance it for social media trends).
        3. 'features': Generate a bulleted list of 5 powerful emotional selling features.
        4. 'specifications': Format the key technical specifications cleanly into a JSON object.
        5. 'seo_assets': Generate a trending SEO title, a meta description, and 5-10 high-traffic keywords.
        6. 'faq_assets': Compose 3-5 frequently asked questions and answers that overcome customer doubts.
        7. 'reviews_assets' & 'back_reviews': Author 3-5 realistic, high-quality positive customer reviews.

        Return ONLY a clean JSON object with this exact structure:
        {{
            "name": "AI Generated Trending Name",
            "images": ["Scraped URL 1", "Scraped URL 2", "..."],
            "videos": ["Scraped Video URL 1", "..."],
            "description": "AI Generated Marketing Description",
            "features": ["Feature 1", "Feature 2"],
            "specifications": {{"Color": "Black", "Size": "M"}},
            "seo_assets": {{"title": "", "description": "", "keywords": []}},
            "faq_assets": [{{"q": "", "a": ""}}],
            "reviews_assets": ["Review 1", "Review 2"],
            "rating": "Scraped Rating",
            "back_reviews": "AI Generated Back Reviews Summary"
        }}

        Raw HTML Context: {raw_html}
        """

        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={gemini_key}"
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        gemini_response = requests.post(gemini_url, headers=headers, json=payload)
        gemini_data = gemini_response.json()

        if "candidates" not in gemini_data:
            return {"status": "error", "message": "جوجل رفضت الطلب", "google_error": gemini_data}
        
        ai_text = gemini_data["candidates"][0]["content"]["parts"][0]["text"]
        ai_text = ai_text.replace("```json", "").replace("```", "").strip()
        
        data = json.loads(ai_text)
        return {"status": "success", "data": data}

    except Exception as e:
        return {"status": "error", "message": str(e)}
