import os
import json
import re
import time
from typing import Any
from html import unescape

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl


app = FastAPI(title="ShwayGo Engine API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScrapeRequest(BaseModel):
    url: HttpUrl


def clean_image_url(url: str) -> str:
    if not url:
        return ""

    url = unescape(str(url))
    url = url.strip().replace("\\/", "/").replace("\\u002F", "/")

    if url.startswith("//"):
        url = f"https:{url}"
    elif url.startswith("http://"):
        url = url.replace("http://", "https://", 1)

    # إزالة علامات أو أحرف زائدة من نهاية الرابط
    url = url.rstrip("\\\"',;)]}")

    return url


def is_likely_product_image(url: str) -> bool:
    if not url.startswith("https://"):
        return False

    lowered = url.lower()

    blocked_parts = [
        "logo",
        "avatar",
        "icon",
        "favicon",
        "sprite",
        "banner",
        "placeholder",
        "tracking",
        "analytics",
        "pixel.",
    ]

    return not any(part in lowered for part in blocked_parts)


def extract_images_from_html(html: str) -> list[str]:
    patterns = [
        r'https?:\\?/\\?/[^"\'\s<>]+?\.(?:jpg|jpeg|png|webp)(?:\?[^"\'\s<>]*)?',
        r'//[^"\'\s<>]+?\.(?:jpg|jpeg|png|webp)(?:\?[^"\'\s<>]*)?',
        r'"imageUrl"\s*:\s*"([^"]+)"',
        r'"imagePath"\s*:\s*"([^"]+)"',
        r'"src"\s*:\s*"([^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
    ]

    found: list[str] = []

    for pattern in patterns:
        for match in re.findall(pattern, html, flags=re.IGNORECASE):
            image_url = match if isinstance(match, str) else match[0]
            image_url = clean_image_url(image_url)

            if (
                image_url
                and is_likely_product_image(image_url)
                and image_url not in found
            ):
                found.append(image_url)

    return found[:20]


def extract_title_from_html(html: str) -> str:
    patterns = [
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title',
        r"<title[^>]*>(.*?)</title>",
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            title = unescape(match.group(1))
            title = re.sub(r"<[^>]+>", " ", title)
            title = re.sub(r"\s+", " ", title).strip()

            if title:
                return title[:300]

    return "Product from supplier link"


def safe_rating(value: Any) -> float:
    try:
        cleaned = re.sub(r"[^0-9.]", "", str(value or "0"))
        rating = float(cleaned or 0)

        if rating < 0:
            return 0.0
        if rating > 5:
            return 5.0

        return rating
    except (TypeError, ValueError):
        return 0.0


def normalize_string(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)

    return str(value)


def join_string_list(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(
            normalize_string(item)
            for item in value
            if normalize_string(item)
        )

    return normalize_string(value)


def normalize_images(value: Any, fallback_images: list[str]) -> list[str]:
    images: list[str] = []

    if isinstance(value, list):
        for item in value:
            image_url = clean_image_url(normalize_string(item))

            if (
                image_url
                and is_likely_product_image(image_url)
                and image_url not in images
            ):
                images.append(image_url)

    # نضيف الصور المستخرجة بالكود إذا نسي Gemini بعضها
    for image_url in fallback_images:
        if image_url not in images:
            images.append(image_url)

    return images[:20]


def build_fallback_data(raw_html: str) -> dict[str, Any]:
    return {
        "names": extract_title_from_html(raw_html),
        "description": (
            "The supplier page was extracted successfully, but AI content "
            "generation was temporarily unavailable. Review and edit the "
            "original product information."
        ),
        "key_features": (
            "Supplier page extracted successfully\n"
            "Original product images collected\n"
            "AI content temporarily unavailable"
        ),
        "specifications": "Not found",
        "seo_keywords": "",
        "faqs": "",
        "reviews_text": "",
        "product_rating": 0.0,
        "images": extract_images_from_html(raw_html),
        "videos_link": "",
    }


def flatten_success_response(
    data: dict[str, Any],
    source: str,
    **extra: Any,
) -> dict[str, Any]:
    """
    يعيد الحقول بطريقتين:
    1) في المستوى الأول: $.description
    2) داخل data: $.data.description
    """

    response = {
        "status": "success",
        "source": source,

        # الحقول المباشرة التي سيقرأها FlutterFlow
        "names": data.get("names", ""),
        "description": data.get("description", ""),
        "key_features": data.get("key_features", ""),
        "specifications": data.get("specifications", ""),
        "seo_keywords": data.get("seo_keywords", ""),
        "faqs": data.get("faqs", ""),
        "reviews_text": data.get("reviews_text", ""),
        "product_rating": data.get("product_rating", 0.0),
        "images": data.get("images", []),
        "videos_link": data.get("videos_link", ""),

        # إبقاء التنسيق القديم للتوافق
        "data": data,
    }

    response.update(extra)
    return response


def call_gemini(
    gemini_key: str,
    prompt: str,
    max_attempts: int = 3,
) -> dict[str, Any]:
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    gemini_url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={gemini_key}"
    )

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING"},
            "images": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
            },
            "videos": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
            },
            "description": {"type": "STRING"},
            "features": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
            },
            "specifications": {
                "type": "OBJECT",
                "additionalProperties": {"type": "STRING"},
            },
            "seo_assets": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "keywords": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                },
                "required": ["title", "description", "keywords"],
            },
            "faq_assets": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "q": {"type": "STRING"},
                        "a": {"type": "STRING"},
                    },
                    "required": ["q", "a"],
                },
            },
            "reviews_assets": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
            },
            "rating": {"type": "NUMBER"},
        },
        "required": [
            "name",
            "images",
            "videos",
            "description",
            "features",
            "specifications",
            "seo_assets",
            "faq_assets",
            "reviews_assets",
            "rating",
        ],
    }

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
            "temperature": 0.2,
            "maxOutputTokens": 8192,
        },
    }

    last_error: dict[str, Any] = {}

    for attempt in range(max_attempts):
        try:
            response = requests.post(
                gemini_url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )

            try:
                response_data = response.json()
            except ValueError:
                response_data = {
                    "http_status": response.status_code,
                    "raw_response": response.text[:1000],
                }

            if response.status_code == 200 and "candidates" in response_data:
                text = response_data["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)

            last_error = response_data

            # إعادة المحاولة عند الضغط أو الأخطاء المؤقتة
            if response.status_code not in {429, 500, 502, 503, 504}:
                break

            time.sleep(2 * (attempt + 1))

        except requests.RequestException as exc:
            last_error = {"request_error": str(exc)}
            time.sleep(2 * (attempt + 1))

    raise RuntimeError(
        f"Gemini failed after {max_attempts} attempts: "
        f"{json.dumps(last_error, ensure_ascii=False)[:1500]}"
    )


@app.get("/")
def health_check():
    return {
        "status": "ok",
        "service": "ShwayGo Engine API",
        "version": "2.0.0",
    }


@app.post("/scrape")
def scrape(request: ScrapeRequest):
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    scrapingant_key = os.environ.get("SCRAPINGANT_API_KEY", "").strip()

    if not scrapingant_key:
        return {
            "status": "error",
            "message": "Missing SCRAPINGANT_API_KEY",
        }

    product_url = str(request.url)

    try:
        scrape_response = requests.get(
            "https://api.scrapingant.com/v2/general",
            params={
                "url": product_url,
                "x-api-key": scrapingant_key,
                "browser": "true",
            },
            timeout=120,
        )

        raw_html = scrape_response.text[:120000]

        if scrape_response.status_code != 200:
            return {
                "status": "error",
                "message": "ScrapingAnt request failed",
                "scraping_status": scrape_response.status_code,
                "scraping_preview": raw_html[:800],
            }

        blocked_words = [
            "zenrows web scraping api",
            "trial expired",
            "auth005",
            "missing api token",
            "invalid api token",
            "subscription renewal",
        ]

        raw_html_lower = raw_html.lower()

        if any(word in raw_html_lower for word in blocked_words):
            return {
                "status": "error",
                "message": "Scraper returned a service/error page instead of the product",
                "scraping_preview": raw_html[:1000],
            }

        extracted_images = extract_images_from_html(raw_html)
        extracted_title = extract_title_from_html(raw_html)

        if not gemini_key:
            fallback = build_fallback_data(raw_html)

            return flatten_success_response(
                fallback,
                source="fallback_no_gemini_key",
                product_url=product_url,
            )

        prompt = f"""
You are ShwayGo Engine, an e-commerce product preparation system.

Analyze the supplier product page HTML and return accurate product data.

STRICT RULES:
1. Never invent original product facts.
2. Product specifications, material, colors, sizes, origin, rating,
   images and videos must come only from the supplied HTML.
3. If an original fact is unavailable, return "Not found", an empty
   string, an empty array, or 0 as appropriate.
4. The description, features, SEO and FAQ may be professionally
   improved using the verified product information.
5. Return only valid JSON matching the supplied JSON schema.
6. Do not use Markdown.

Known title extracted by the server:
{extracted_title}

Known image URLs extracted by the server:
{json.dumps(extracted_images, ensure_ascii=False)}

RAW HTML:
{raw_html}
"""

        try:
            gemini_data = call_gemini(gemini_key, prompt)

            final_data = {
                "names": normalize_string(gemini_data.get("name")),
                "description": normalize_string(
                    gemini_data.get("description")
                ),
                "key_features": join_string_list(
                    gemini_data.get("features")
                ),
                "specifications": json.dumps(
                    gemini_data.get("specifications", {}),
                    ensure_ascii=False,
                ),
                "seo_keywords": ", ".join(
                    gemini_data.get("seo_assets", {}).get("keywords", [])
                )
                if isinstance(gemini_data.get("seo_assets"), dict)
                else "",
                "faqs": "\n".join(
                    f"Q: {item.get('q', '')}\nA: {item.get('a', '')}"
                    for item in gemini_data.get("faq_assets", [])
                    if isinstance(item, dict)
                ),
                "reviews_text": join_string_list(
                    gemini_data.get("reviews_assets")
                ),
                "product_rating": safe_rating(
                    gemini_data.get("rating")
                ),
                "images": normalize_images(
                    gemini_data.get("images"),
                    extracted_images,
                ),
                "videos_link": join_string_list(
                    gemini_data.get("videos")
                ),
            }

            if not final_data["names"]:
                final_data["names"] = extracted_title

            return flatten_success_response(
                final_data,
                source="gemini",
                product_url=product_url,
            )

        except Exception as gemini_error:
            fallback = build_fallback_data(raw_html)

            return flatten_success_response(
                fallback,
                source="fallback_gemini_failed",
                product_url=product_url,
                gemini_error=str(gemini_error)[:1500],
            )

    except requests.Timeout:
        return {
            "status": "error",
            "message": "The scraping request timed out",
        }

    except requests.RequestException as exc:
        return {
            "status": "error",
            "message": "Network request failed",
            "details": str(exc),
        }

    except Exception as exc:
        return {
            "status": "error",
            "message": "Unexpected server error",
            "details": str(exc),
        }
