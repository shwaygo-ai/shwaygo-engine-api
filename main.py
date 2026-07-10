import os
import json
import re
import time
from html import unescape
from typing import Any

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl


# =========================================================
# APP SETUP
# =========================================================

app = FastAPI(
    title="ShwayGo Engine API",
    version="3.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScrapeRequest(BaseModel):
    url: HttpUrl


# =========================================================
# CONSTANTS
# =========================================================

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_INTERACTIONS_URL = (
    "https://generativelanguage.googleapis.com/v1beta/interactions"
)
MAX_HTML_CHARS = 100_000
MAX_IMAGES = 20


# =========================================================
# GENERAL HELPERS
# =========================================================

def normalize_text(value: Any) -> str:
    """Always return a clean string, never None."""
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)

    return str(value).strip()


def clean_image_url(url: Any) -> str:
    """Normalize supplier image URLs."""
    if not url:
        return ""

    cleaned = unescape(str(url))
    cleaned = cleaned.strip()
    cleaned = cleaned.replace("\\/", "/")
    cleaned = cleaned.replace("\\u002F", "/")
    cleaned = cleaned.replace("&amp;", "&")

    if cleaned.startswith("//"):
        cleaned = "https:" + cleaned
    elif cleaned.startswith("http://"):
        cleaned = cleaned.replace("http://", "https://", 1)

    cleaned = cleaned.rstrip("\\\"',;)]}")

    return cleaned


def is_product_image(url: str) -> bool:
    """Reject obvious icons, logos, placeholders and tracking pixels."""
    if not url.startswith("https://"):
        return False

    lowered = url.lower()

    blocked_terms = [
        "favicon",
        "sprite",
        "avatar",
        "tracking",
        "analytics",
        "pixel.",
        "placeholder",
        "loading.",
        "logo.",
        "/logo/",
        "/icon/",
        "spacer.",
        "transparent.",
    ]

    return not any(term in lowered for term in blocked_terms)


def extract_images_from_html(html: str) -> list[str]:
    """Extract supplier product image candidates directly from HTML."""
    patterns = [
        r'https?:\\?/\\?/[^"\'\s<>]+?\.(?:jpg|jpeg|png|webp)(?:\?[^"\'\s<>]*)?',
        r'//[^"\'\s<>]+?\.(?:jpg|jpeg|png|webp)(?:\?[^"\'\s<>]*)?',
        r'"imageUrl"\s*:\s*"([^"]+)"',
        r'"imagePath"\s*:\s*"([^"]+)"',
        r'"image"\s*:\s*"([^"]+)"',
        r'"src"\s*:\s*"([^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image',
    ]

    images: list[str] = []

    for pattern in patterns:
        matches = re.findall(pattern, html, flags=re.IGNORECASE)

        for match in matches:
            candidate = match if isinstance(match, str) else match[0]
            candidate = clean_image_url(candidate)

            if (
                candidate
                and is_product_image(candidate)
                and candidate not in images
            ):
                images.append(candidate)

    return images[:MAX_IMAGES]


def extract_title_from_html(html: str) -> str:
    """Extract an original supplier title without AI invention."""
    patterns = [
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title',
        r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)',
        r"<title[^>]*>(.*?)</title>",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if not match:
            continue

        title = unescape(match.group(1))
        title = re.sub(r"<[^>]+>", " ", title)
        title = re.sub(r"\s+", " ", title).strip()

        if title:
            return title[:300]

    return "Product from supplier link"


def safe_rating(value: Any) -> float:
    """Always return a valid rating between 0 and 5."""
    try:
        match = re.search(r"\d+(?:\.\d+)?", str(value or "0"))

        if not match:
            return 0.0

        rating = float(match.group(0))
        return max(0.0, min(rating, 5.0))

    except (TypeError, ValueError):
        return 0.0


def join_lines(value: Any) -> str:
    """Convert lists to a newline-separated Firestore String."""
    if isinstance(value, list):
        items: list[str] = []

        for item in value:
            text = normalize_text(item)
            if text:
                items.append(text)

        return "\n".join(items)

    return normalize_text(value)


def format_specifications(value: Any) -> str:
    """
    Convert Gemini specifications into a Firestore String.
    Accepts dictionaries or arrays of {key, value}.
    """
    lines: list[str] = []

    if isinstance(value, dict):
        for key, item_value in value.items():
            key_text = normalize_text(key)
            value_text = normalize_text(item_value)

            if key_text and value_text:
                lines.append(f"{key_text}: {value_text}")

    elif isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue

            key_text = normalize_text(
                item.get("key")
                or item.get("name")
                or item.get("label")
            )

            value_text = normalize_text(
                item.get("value")
                or item.get("text")
            )

            if key_text and value_text:
                lines.append(f"{key_text}: {value_text}")

    elif value:
        return normalize_text(value)

    return "\n".join(lines) if lines else "Not found"


def format_faqs(value: Any) -> str:
    """Convert FAQ array into one Firestore String."""
    if not isinstance(value, list):
        return normalize_text(value)

    items: list[str] = []

    for item in value:
        if not isinstance(item, dict):
            continue

        question = normalize_text(
            item.get("q") or item.get("question")
        )
        answer = normalize_text(
            item.get("a") or item.get("answer")
        )

        if question or answer:
            items.append(f"Q: {question}\nA: {answer}")

    return "\n\n".join(items)


def normalize_images(
    ai_images: Any,
    extracted_images: list[str],
) -> list[str]:
    """Merge AI-selected supplier images with server-extracted images."""
    final_images: list[str] = []

    if isinstance(ai_images, list):
        for item in ai_images:
            image_url = clean_image_url(item)

            if (
                image_url
                and is_product_image(image_url)
                and image_url not in final_images
            ):
                final_images.append(image_url)

    for image_url in extracted_images:
        if image_url not in final_images:
            final_images.append(image_url)

    return final_images[:MAX_IMAGES]


# =========================================================
# RESPONSE BUILDERS
# =========================================================

def empty_product_data() -> dict[str, Any]:
    """
    Fixed response types for FlutterFlow.
    No field is ever returned as null.
    """
    return {
        "names": "",
        "description": "",
        "key_features": "",
        "specifications": "",
        "seo_keywords": "",
        "faqs": "",
        "reviews_text": "",
        "product_rating": 0.0,
        "images": [],
        "videos_link": "",
    }


def build_fallback_data(raw_html: str) -> dict[str, Any]:
    """Original-data fallback if Gemini is unavailable."""
    data = empty_product_data()

    data.update(
        {
            "names": extract_title_from_html(raw_html),
            "description": (
                "The supplier page was extracted successfully, "
                "but AI content generation was temporarily unavailable. "
                "Review and edit the original product information."
            ),
            "key_features": (
                "Supplier page extracted successfully\n"
                "Original product title collected\n"
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
    )

    return data


def success_response(
    data: dict[str, Any],
    source: str,
    product_url: str,
    **extra: Any,
) -> dict[str, Any]:
    """
    FlutterFlow receives every field at the top level.
    A copy remains under $.data for backward compatibility.
    """
    normalized = empty_product_data()

    normalized.update(
        {
            "names": normalize_text(data.get("names")),
            "description": normalize_text(data.get("description")),
            "key_features": normalize_text(data.get("key_features")),
            "specifications": normalize_text(data.get("specifications")),
            "seo_keywords": normalize_text(data.get("seo_keywords")),
            "faqs": normalize_text(data.get("faqs")),
            "reviews_text": normalize_text(data.get("reviews_text")),
            "product_rating": safe_rating(data.get("product_rating")),
            "images": (
                data.get("images")
                if isinstance(data.get("images"), list)
                else []
            ),
            "videos_link": normalize_text(data.get("videos_link")),
        }
    )

    response = {
        "status": "success",
        "source": source,
        "product_url": product_url,
        **normalized,
        "data": normalized,
    }

    response.update(extra)
    return response


def error_response(message: str, **extra: Any) -> dict[str, Any]:
    response = {
        "status": "error",
        "message": message,
    }
    response.update(extra)
    return response


# =========================================================
# SCRAPINGANT
# =========================================================

def fetch_supplier_html(
    product_url: str,
    scrapingant_key: str,
) -> str:
    """Fetch rendered supplier HTML using ScrapingAnt."""
    response = requests.get(
        "https://api.scrapingant.com/v2/general",
        params={
            "url": product_url,
            "x-api-key": scrapingant_key,
            "browser": "true",
        },
        timeout=120,
    )

    html = response.text

    if response.status_code != 200:
        raise RuntimeError(
            "ScrapingAnt failed with HTTP "
            f"{response.status_code}: {html[:700]}"
        )

    if not html or len(html.strip()) < 200:
        raise RuntimeError(
            "ScrapingAnt returned an empty or incomplete page."
        )

    lowered = html.lower()

    service_error_terms = [
        "zenrows web scraping api",
        "trial expired",
        "auth005",
        "missing api token",
        "invalid api token",
        "subscription expired",
        "payment required",
    ]

    if any(term in lowered for term in service_error_terms):
        raise RuntimeError(
            "The scraper returned a service/error page "
            "instead of the supplier product page."
        )

    return html[:MAX_HTML_CHARS]


# =========================================================
# GEMINI
# =========================================================

def gemini_response_schema() -> dict[str, Any]:
    """
    Standard JSON Schema for Gemini structured output.
    Lowercase JSON Schema types are used intentionally.
    """
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "features": {
                "type": "array",
                "items": {"type": "string"},
            },
            "specifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                    },
                    "required": ["key", "value"],
                    "additionalProperties": False,
                },
            },
            "seo_keywords": {
                "type": "array",
                "items": {"type": "string"},
            },
            "faqs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "q": {"type": "string"},
                        "a": {"type": "string"},
                    },
                    "required": ["q", "a"],
                    "additionalProperties": False,
                },
            },
            "reviews": {
                "type": "array",
                "items": {"type": "string"},
            },
            "rating": {
                "type": "number",
                "minimum": 0,
                "maximum": 5,
            },
            "images": {
                "type": "array",
                "items": {"type": "string"},
            },
            "videos": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "name",
            "description",
            "features",
            "specifications",
            "seo_keywords",
            "faqs",
            "reviews",
            "rating",
            "images",
            "videos",
        ],
        "additionalProperties": False,
    }


def extract_google_error(response_data: Any) -> str:
    """Return a readable Gemini error without exposing the API key."""
    if isinstance(response_data, dict):
        error = response_data.get("error")

        if isinstance(error, dict):
            code = normalize_text(error.get("code"))
            status = normalize_text(error.get("status"))
            message = normalize_text(error.get("message"))

            parts = [
                part
                for part in [code, status, message]
                if part
            ]

            if parts:
                return " | ".join(parts)

        return json.dumps(
            response_data,
            ensure_ascii=False,
        )[:1500]

    return normalize_text(response_data)[:1500]


def extract_interaction_text(response_data: dict[str, Any]) -> str:
    """Extract text from the Interactions API steps response."""
    steps = response_data.get("steps", [])

    if not isinstance(steps, list):
        return ""

    text_parts: list[str] = []

    for step in steps:
        if not isinstance(step, dict):
            continue

        if step.get("type") != "model_output":
            continue

        content = step.get("content", [])

        if not isinstance(content, list):
            continue

        for item in content:
            if not isinstance(item, dict):
                continue

            if item.get("type") == "text":
                text = normalize_text(item.get("text"))
                if text:
                    text_parts.append(text)

    return "\n".join(text_parts).strip()


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse Gemini JSON safely and require a top-level object."""
    cleaned = normalize_text(text)
    cleaned = cleaned.replace("```json", "")
    cleaned = cleaned.replace("```JSON", "")
    cleaned = cleaned.replace("```", "")
    cleaned = cleaned.strip()

    if not cleaned:
        raise RuntimeError("Gemini returned empty text.")

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")

        if first_brace == -1 or last_brace == -1:
            raise RuntimeError(
                "Gemini response did not contain a JSON object."
            )

        parsed = json.loads(cleaned[first_brace:last_brace + 1])

    if not isinstance(parsed, dict):
        raise RuntimeError(
            "Gemini JSON output was not an object."
        )

    return parsed


def call_gemini(
    api_key: str,
    prompt: str,
) -> tuple[dict[str, Any], str]:
    """
    Call the official Gemini Interactions API with retries.
    Returns: (parsed_json, model_used)
    """
    model = (
        os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
        or DEFAULT_GEMINI_MODEL
    )

    payload = {
        "model": model,
        "input": prompt,
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": gemini_response_schema(),
        },
        "generation_config": {
            "temperature": 0.15,
            "thinking_level": "low",
            "max_output_tokens": 8192,
        },
        "store": False,
    }

    last_error = "Unknown Gemini error."

    for attempt in range(1, 4):
        try:
            response = requests.post(
                GEMINI_INTERACTIONS_URL,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
                json=payload,
                timeout=150,
            )

            try:
                response_data = response.json()
            except ValueError:
                response_data = {
                    "raw_response": response.text[:1500],
                }

            if response.status_code == 200:
                if not isinstance(response_data, dict):
                    raise RuntimeError(
                        "Gemini returned an invalid response object."
                    )

                status = normalize_text(response_data.get("status"))

                if status and status != "completed":
                    raise RuntimeError(
                        f"Gemini interaction status was {status}."
                    )

                output_text = extract_interaction_text(response_data)

                if not output_text:
                    raise RuntimeError(
                        "Gemini returned no model_output text."
                    )

                return parse_json_object(output_text), model

            last_error = (
                f"HTTP {response.status_code}: "
                f"{extract_google_error(response_data)}"
            )

            if response.status_code in {
                408,
                429,
                500,
                502,
                503,
                504,
            }:
                if attempt < 3:
                    time.sleep(attempt * 3)
                    continue

            break

        except requests.RequestException as exc:
            last_error = f"Network error: {exc}"

            if attempt < 3:
                time.sleep(attempt * 3)
                continue

        except (json.JSONDecodeError, RuntimeError) as exc:
            last_error = str(exc)

            if attempt < 3:
                time.sleep(attempt * 3)
                continue

    raise RuntimeError(
        "Gemini request failed after 3 attempts. "
        f"Model: {model}. Last error: {last_error[:1500]}"
    )


def build_gemini_prompt(
    raw_html: str,
    original_title: str,
    original_images: list[str],
) -> str:
    """Build a fact-preserving product extraction prompt."""
    return f"""
You are ShwayGo Engine, a professional e-commerce product preparation system.

Your responsibilities:

A) Preserve original supplier facts.
B) Create high-quality marketing content only from verified facts.

STRICT RULES:

1. Do not invent colors, sizes, materials, country of origin,
   dimensions, ratings, reviews, images, or videos.

2. Original facts must come only from the supplied HTML or from the
   server-extracted title and image URLs below.

3. If an original fact is missing:
   - return an empty array for lists,
   - return an empty string for text,
   - return 0 for rating,
   - or return a specification item whose value is "Not found"
     only when a specification category exists but its value is unavailable.

4. You may improve:
   - product title,
   - marketing description,
   - selling features,
   - SEO keywords,
   - FAQ wording.

5. Reviews must be extracted from the supplier page only.
   Never create fake customer reviews.

6. Images must be supplier product image URLs only.

7. Videos must be supplier video URLs only.
   Never invent a video URL.

8. Return valid JSON matching the required schema only.

SERVER-EXTRACTED ORIGINAL TITLE:
{original_title}

SERVER-EXTRACTED IMAGE URLS:
{json.dumps(original_images, ensure_ascii=False)}

SUPPLIER HTML:
{raw_html}
""".strip()


def normalize_gemini_data(
    gemini_data: dict[str, Any],
    original_title: str,
    extracted_images: list[str],
) -> dict[str, Any]:
    """Convert Gemini output to the exact FlutterFlow field types."""
    data = empty_product_data()
    seo_keywords = gemini_data.get("seo_keywords", [])

    data.update(
        {
            "names": (
                normalize_text(gemini_data.get("name"))
                or original_title
            ),
            "description": normalize_text(
                gemini_data.get("description")
            ),
            "key_features": join_lines(
                gemini_data.get("features")
            ),
            "specifications": format_specifications(
                gemini_data.get("specifications")
            ),
            "seo_keywords": (
                ", ".join(
                    normalize_text(item)
                    for item in seo_keywords
                    if normalize_text(item)
                )
                if isinstance(seo_keywords, list)
                else normalize_text(seo_keywords)
            ),
            "faqs": format_faqs(
                gemini_data.get("faqs")
            ),
            "reviews_text": join_lines(
                gemini_data.get("reviews")
            ),
            "product_rating": safe_rating(
                gemini_data.get("rating")
            ),
            "images": normalize_images(
                gemini_data.get("images"),
                extracted_images,
            ),
            "videos_link": join_lines(
                gemini_data.get("videos")
            ),
        }
    )

    return data


# =========================================================
# ROUTES
# =========================================================

@app.get("/")
def health_check():
    model = (
        os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
        or DEFAULT_GEMINI_MODEL
    )

    return {
        "status": "ok",
        "service": "ShwayGo Engine API",
        "version": "3.1.0",
        "gemini_api": "interactions_v1beta",
        "gemini_model": model,
    }


@app.post("/scrape")
def scrape(request: ScrapeRequest):
    product_url = str(request.url)

    gemini_key = os.environ.get(
        "GEMINI_API_KEY",
        "",
    ).strip()

    scrapingant_key = os.environ.get(
        "SCRAPINGANT_API_KEY",
        "",
    ).strip()

    configured_model = (
        os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
        or DEFAULT_GEMINI_MODEL
    )

    if not scrapingant_key:
        return error_response(
            "Missing SCRAPINGANT_API_KEY."
        )

    try:
        raw_html = fetch_supplier_html(
            product_url=product_url,
            scrapingant_key=scrapingant_key,
        )

    except Exception as exc:
        return error_response(
            "Supplier page extraction failed.",
            details=str(exc)[:1500],
        )

    original_title = extract_title_from_html(raw_html)
    original_images = extract_images_from_html(raw_html)

    if not gemini_key:
        fallback = build_fallback_data(raw_html)

        return success_response(
            data=fallback,
            source="fallback_no_gemini_key",
            product_url=product_url,
            gemini_model=configured_model,
        )

    prompt = build_gemini_prompt(
        raw_html=raw_html,
        original_title=original_title,
        original_images=original_images,
    )

    try:
        gemini_data, model_used = call_gemini(
            api_key=gemini_key,
            prompt=prompt,
        )

        final_data = normalize_gemini_data(
            gemini_data=gemini_data,
            original_title=original_title,
            extracted_images=original_images,
        )

        return success_response(
            data=final_data,
            source="gemini",
            product_url=product_url,
            gemini_model=model_used,
            gemini_api="interactions_v1beta",
        )

    except Exception as exc:
        fallback = build_fallback_data(raw_html)

        return success_response(
            data=fallback,
            source="fallback_gemini_failed",
            product_url=product_url,
            gemini_model=configured_model,
            gemini_api="interactions_v1beta",
            gemini_error=str(exc)[:1500],
        )
