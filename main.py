import os
import json
import re
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


def clean_image_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip().replace("\\/", "/")
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("http://"):
        url = url.replace("http://", "https://", 1)
    return url


def extract_images_from_html(html: str):
    found = re.findall(r'https?:\/\/[^"\']+\.(?:jpg|jpeg|png|webp)', html)
    found += re.findall(r'\/\/[^"\']+\.(?:jpg|jpeg|png|webp)', html)

    images = []
    for img in found:
        img = clean_image_url(img)
        if img and img not in images:
            images.append(img)

    return images[:10]


def fallback_data(raw_html: str, url: str):
    images = extract_images_from_html(raw_html)

    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else "Product from supplier link"
    title = re.sub(r"\s+", " ", title)

    return {
        "names": title[:180],
        "description": "Original product data was extracted from the supplier page. AI generation was temporarily unavailable, so this is a fallback package for testing.",
        "key_features": "AI temporarily unavailable\nSource page extracted successfully\nReview and edit this product manually",
        "specifications": "Not fully extracted yet",
        "seo_keywords": "",
        "faqs": "",
        "reviews_text": "",
        "product_rating": 0.0,
        "images": images,
        "videos_link": "",
    }


@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    try:
        gemini_key = os.environ.get("GEMINI_API_KEY")
        scrapingant_key = os.environ.get("SCRAPINGANT_API_KEY")

        if not scrapingant_key:
            return {"status": "error", "message": "Missing SCRAPINGANT_API_KEY"}

        scrape_response = requests.get(
            "https://api.scrapingant.com/v2/general",
            params={
                "url": request.url,
                "x-api-key": scrapingant_key,
                "browser": "true",
            },
            timeout=90,
        )

        raw_html = scrape_response.text[:80000]

        if scrape_response.status_code != 200:
            return {
                "status": "error",
                "message": "ScrapingAnt failed",
                "scraping_status": scrape_response.status_code,
                "scraping_preview": raw_html[:500],
            }

        blocked_words = [
            "ScrapingAnt",
            "ZenRows Web Scraping API",
            "subscription",
            "AUTH005",
            "Trial expired",
            "API token",
        ]

        if any(word.lower() in raw_html.lower() for word in blocked_words):
            return {
                "status": "error",
                "message": "Scraper returned service page, not product page",
                "scraping_preview": raw_html[:800],
            }

        if not gemini_key:
            return {
                "status": "success",
                "data": fallback_data(raw_html, request.url),
                "source": "fallback_no_gemini_key",
            }

        prompt = f"""
You are ShwayGo Engine, an e-commerce product package generator.

Extract and generate product data from the provided HTML.

Important rules:
- Return ONLY valid JSON.
- No markdown.
- No explanation.
- Do not invent original product facts.
- If a real product fact is not found, write "Not found".
- Use supplier images only if found in HTML.

Use this exact JSON structure:

{{
  "name": "Optimized product name",
  "images": ["image_url_1", "image_url_2"],
  "videos": ["video_url_1"],
  "description": "Marketing product description",
  "features": ["Feature 1", "Feature 2", "Feature 3", "Feature 4", "Feature 5"],
  "specifications": {{"Color": "Not found", "Size": "Not found", "Material": "Not found", "Origin": "Not found"}},
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
  "rating": "0"
}}

Raw HTML:
{raw_html}
"""

        gemini_url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-3.5-flash:generateContent?key={gemini_key}"
        )

        gemini_response = requests.post(
            gemini_url,
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=90,
        )

        gemini_data = gemini_response.json()

        if "candidates" not in gemini_data:
            return {
                "status": "success",
                "data": fallback_data(raw_html, request.url),
                "source": "fallback_gemini_failed",
                "gemini_error": gemini_data,
            }

        ai_text = gemini_data["candidates"][0]["content"]["parts"][0]["text"]
        ai_text = ai_text.replace("```json", "").replace("```", "").strip()

        data = json.loads(ai_text)

        images = data.get("images", [])
        if not isinstance(images, list) or len(images) == 0:
            images = extract_images_from_html(raw_html)

        final_data = {
            "names": data.get("name", ""),
            "description": data.get("description", ""),
            "key_features": "\n".join(data.get("features", []))
            if isinstance(data.get("features"), list)
            else str(data.get("features", "")),
            "specifications": json.dumps(data.get("specifications", {}), ensure_ascii=False),
            "seo_keywords": ", ".join(data.get("seo_assets", {}).get("keywords", []))
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
            "product_rating": float(str(data.get("rating", "0")).replace("/5", "").strip() or 0),
            "images": images if isinstance(images, list) else [],
            "videos_link": "\n".join(data.get("videos", []))
            if isinstance(data.get("videos"), list)
            else str(data.get("videos", "")),
        }

        return {"status": "success", "data": final_data, "source": "gemini"}

    except Exception as e:
        return {
            "status": "success",
            "data": {
                "names": "Fallback product",
                "description": "Temporary fallback data because the server had an exception.",
                "key_features": "Fallback mode\nServer exception handled\nContinue testing FlutterFlow",
                "specifications": "Not found",
                "seo_keywords": "",
                "faqs": "",
                "reviews_text": "",
                "product_rating": 0.0,
                "images": [],
                "videos_link": "",
            },
            "source": "fallback_exception",
            "message": str(e),
        }
