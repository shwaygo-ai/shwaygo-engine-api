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

        zenrows_params = {
            "apikey": zenrows_key,
            "url": request.url,
            "js_render": "true",
        }

        response = requests.get(
            "https://api.zenrows.com/v1/",
            params=zenrows_params,
            timeout=60,
        )

        raw_html = response.text[:80000]

        prompt = f"""
You are ShwayGo Engine, an e-commerce product package generator.

Extract and generate product data from the provided HTML.

Return ONLY valid JSON. No markdown. No explanation.

Use this exact JSON structure:

{{
  "name": "Optimized product name",
  "images": ["image_url_1", "image_url_2"],
  "videos": ["video_url_1"],
  "description": "Marketing product description",
  "features": ["Feature 1", "Feature 2", "Feature 3", "Feature 4", "Feature 5"],
  "specifications": {{"Color": "Black", "Size": "M"}},
  "seo_assets": {{
    "title": "SEO title",
    "description": "SEO meta description",
    "keywords": ["keyword 1", "keyword 2"]
  }},
  "faq_assets": [
    {{"q": "Question 1", "a": "Answer 1"}},
    {{"q": "Question 2", "a": "Answer 2"}}
  ],
  "reviews_assets": ["Review 1", "Review 2", "Review 3"],
  "rating": "4.8"
}}

Raw HTML:
{raw_html}
"""

        gemini_url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-3.5-flash:generateContent?key={gemini_key}"
        )

        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}

        gemini_response = requests.post(
            gemini_url,
            headers=headers,
            json=payload,
            timeout=90,
        )

        gemini_data = gemini_response.json()

        if "candidates" not in gemini_data:
            return {
                "status": "error",
                "message": "جوجل رفضت الطلب",
                "google_error": gemini_data,
            }

        ai_text = gemini_data["candidates"][0]["content"]["parts"][0]["text"]
        ai_text = ai_text.replace("```json", "").replace("```", "").strip()

        data = json.loads(ai_text)

        final_data = {
            "names": data.get("name", ""),
            "description": data.get("description", ""),
            "key_features": "\n".join(data.get("features", []))
            if isinstance(data.get("features"), list)
            else str(data.get("features", "")),
            "specifications": json.dumps(
                data.get("specifications", {}),
                ensure_ascii=False,
            ),
            "seo_keywords": ", ".join(
                data.get("seo_assets", {}).get("keywords", [])
            )
            if isinstance(data.get("seo_assets"), dict)
            else "",
            "faqs": "\n".join(
                [
                    f"Q: {item.get('q', '')}\nA: {item.get('a', '')}"
                    for item in data.get("faq_assets", [])
                    if isinstance(item, dict)
                ]
            )
            if isinstance(data.get("faq_assets"), list)
            else "",
            "reviews_text": "\n".join(data.get("reviews_assets", []))
            if isinstance(data.get("reviews_assets"), list)
            else str(data.get("reviews_assets", "")),
            "product_rating": float(
                str(data.get("rating", "0")).replace("/5", "").strip() or 0
            ),
            "images": data.get("images", [])
            if isinstance(data.get("images"), list)
            else [],
            "videos_link": "\n".join(data.get("videos", []))
            if isinstance(data.get("videos"), list)
            else str(data.get("videos", "")),
        }

        return {"status": "success", "data": final_data}

    except Exception as e:
        return {"status": "error", "message": str(e)}
