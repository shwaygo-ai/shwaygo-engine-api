import base64
import json
import os
import re
import time
from html import unescape
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl


# =========================================================
# SHWAYGO ENGINE V4
# =========================================================

app = FastAPI(
    title="ShwayGo Engine API",
    version="4.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScrapeRequest(BaseModel):
    url: HttpUrl


DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_INTERACTIONS_URL = (
    "https://generativelanguage.googleapis.com/v1beta/interactions"
)

MAX_HTML_CHARS_FOR_AI = 0
MAX_IMAGES = 30
MAX_VIDEOS = 10
MAX_REVIEWS = 20
MAX_SPECS = 80
MAX_JSON_BLOBS = 80
REQUEST_TIMEOUT_SCRAPER = 180
REQUEST_TIMEOUT_GEMINI = 150


# =========================================================
# BASIC HELPERS
# =========================================================

def normalize_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        text = unescape(value)
        text = text.replace("\\/", "/")
        text = text.replace("\\u002F", "/")
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    if isinstance(value, (int, float, bool)):
        return str(value)

    return ""


def unique_strings(
    values: Iterable[Any],
    limit: int | None = None,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        text = normalize_text(value)

        if not text:
            continue

        key = text.casefold()

        if key in seen:
            continue

        seen.add(key)
        result.append(text)

        if limit is not None and len(result) >= limit:
            break

    return result


def safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0

    if isinstance(value, int):
        return max(value, 0)

    if isinstance(value, float):
        return max(int(value), 0)

    text = normalize_text(value).replace(",", "")
    match = re.search(r"\d+", text)

    return int(match.group(0)) if match else 0


def safe_rating(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0

    try:
        if isinstance(value, (int, float)):
            rating = float(value)
        else:
            text = normalize_text(value).replace(",", ".")
            match = re.search(r"\d+(?:\.\d+)?", text)

            if not match:
                return 0.0

            rating = float(match.group(0))

        if rating > 5 and rating <= 100:
            rating = rating / 20.0

        return round(max(0.0, min(rating, 5.0)), 2)

    except (TypeError, ValueError):
        return 0.0


def clean_url(value: Any) -> str:
    text = normalize_text(value)

    if not text:
        return ""

    text = text.replace("\\u0026", "&")
    text = text.replace("&amp;", "&")
    text = text.strip("\"' ")

    if text.startswith("//"):
        text = "https:" + text
    elif text.startswith("http://"):
        text = "https://" + text[7:]

    if not text.startswith("https://"):
        return ""

    try:
        parts = urlsplit(text)
        clean_path = parts.path.rstrip("\\\"',;)]}")
        return urlunsplit(
            (
                "https",
                parts.netloc,
                clean_path,
                parts.query,
                "",
            )
        )
    except ValueError:
        return ""


def is_image_url(url: str) -> bool:
    if not url.startswith("https://"):
        return False

    lowered = url.lower()

    blocked = (
        "favicon",
        "sprite",
        "avatar",
        "tracking",
        "analytics",
        "pixel.",
        "placeholder",
        "loading.",
        "/logo/",
        "/icon/",
        "spacer.",
        "transparent.",
        "qrcode",
    )

    if any(term in lowered for term in blocked):
        return False

    image_markers = (
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".avif",
        "alicdn.com",
        "ae01.alicdn.com",
    )

    return any(marker in lowered for marker in image_markers)


def is_video_url(url: str) -> bool:
    lowered = url.lower()

    return (
        url.startswith("https://")
        and (
            ".mp4" in lowered
            or ".m3u8" in lowered
            or "video" in lowered
        )
    )


def join_lines(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(unique_strings(value))

    return normalize_text(value)


def format_faqs(value: Any) -> str:
    if not isinstance(value, list):
        return normalize_text(value)

    blocks: list[str] = []

    for item in value:
        if not isinstance(item, dict):
            continue

        question = normalize_text(
            item.get("q")
            or item.get("question")
        )
        answer = normalize_text(
            item.get("a")
            or item.get("answer")
        )

        if question and answer:
            blocks.append(f"Q: {question}\nA: {answer}")

    return "\n\n".join(blocks)


def format_specs(specs: dict[str, str]) -> str:
    lines: list[str] = []

    for key, value in specs.items():
        key_text = normalize_text(key)
        value_text = normalize_text(value)

        if key_text and value_text:
            lines.append(f"{key_text}: {value_text}")

    return "\n".join(lines) if lines else "Not found"


# =========================================================
# HTML / JSON EXTRACTION HELPERS
# =========================================================

def extract_meta_content(
    html: str,
    *,
    property_name: str | None = None,
    name: str | None = None,
) -> str:
    if property_name:
        patterns = [
            (
                rf'<meta[^>]+property=["\']{re.escape(property_name)}'
                rf'["\'][^>]+content=["\']([^"\']+)'
            ),
            (
                rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+'
                rf'property=["\']{re.escape(property_name)}["\']'
            ),
        ]
    elif name:
        patterns = [
            (
                rf'<meta[^>]+name=["\']{re.escape(name)}'
                rf'["\'][^>]+content=["\']([^"\']+)'
            ),
            (
                rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+'
                rf'name=["\']{re.escape(name)}["\']'
            ),
        ]
    else:
        return ""

    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)

        if match:
            return normalize_text(match.group(1))

    return ""


def extract_title_from_html(html: str) -> str:
    candidates = [
        extract_meta_content(html, property_name="og:title"),
        extract_meta_content(html, name="twitter:title"),
    ]

    title_match = re.search(
        r"<title[^>]*>(.*?)</title>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if title_match:
        candidates.append(title_match.group(1))

    for candidate in candidates:
        title = normalize_text(candidate)

        if title:
            return title[:500]

    return "Product from supplier link"


def balanced_json_slice(
    text: str,
    start_index: int,
) -> str:
    if start_index < 0 or start_index >= len(text):
        return ""

    opening = text[start_index]

    if opening not in "[{":
        return ""

    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escape = False

    for index in range(start_index, len(text)):
        char = text[index]

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False

            continue

        if char == '"':
            in_string = True
            continue

        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1

            if depth == 0:
                return text[start_index:index + 1]

    return ""


def parse_json_text(text: str) -> Any:
    cleaned = text.strip().rstrip(";")

    if not cleaned:
        return None

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    cleaned = cleaned.replace("\\x2F", "/")
    cleaned = cleaned.replace("\\u002F", "/")

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def extract_json_blobs(html: str) -> list[Any]:
    blobs: list[Any] = []
    seen: set[str] = set()

    script_pattern = re.compile(
        r"<script\b[^>]*>(.*?)</script>",
        flags=re.IGNORECASE | re.DOTALL,
    )

    for match in script_pattern.finditer(html):
        body = match.group(1).strip()

        if not body:
            continue

        candidates: list[str] = []

        if body.startswith("{") or body.startswith("["):
            candidates.append(body)

        for marker in (
            "window.runParams",
            "window._dida_config_",
            "window.__INITIAL_STATE__",
            "window.__PRELOADED_STATE__",
            "window.pageData",
            "window.data",
            "runParams",
            "data:",
            "data =",
        ):
            marker_index = body.find(marker)

            if marker_index == -1:
                continue

            brace_indexes = [
                index
                for index in (
                    body.find("{", marker_index),
                    body.find("[", marker_index),
                )
                if index != -1
            ]

            if not brace_indexes:
                continue

            start = min(brace_indexes)
            candidate = balanced_json_slice(body, start)

            if candidate:
                candidates.append(candidate)

        for candidate in candidates:
            if len(candidate) < 2:
                continue

            signature = candidate[:200] + str(len(candidate))

            if signature in seen:
                continue

            parsed = parse_json_text(candidate)

            if parsed is None:
                continue

            seen.add(signature)
            blobs.append(parsed)

            if len(blobs) >= MAX_JSON_BLOBS:
                return blobs

    return blobs


def walk_json(
    value: Any,
    path: tuple[str, ...] = (),
) -> Iterable[tuple[tuple[str, ...], Any]]:
    yield path, value

    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk_json(
                child,
                path + (str(key),),
            )

    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_json(
                child,
                path + (str(index),),
            )


def path_text(path: tuple[str, ...]) -> str:
    return ".".join(path).lower()


def all_walked(blobs: list[Any]) -> list[tuple[tuple[str, ...], Any]]:
    walked: list[tuple[tuple[str, ...], Any]] = []

    for blob in blobs:
        walked.extend(walk_json(blob))

    return walked



def html_to_visible_text(html: str) -> str:
    """Best-effort conversion of rendered HTML into searchable visible text."""
    cleaned = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(
        r"<style\b[^>]*>.*?</style>",
        " ",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(r"<!--.*?-->", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", "\n", cleaned)
    cleaned = unescape(cleaned)
    cleaned = cleaned.replace("\\u002F", "/")
    cleaned = re.sub(r"[\t\r\f\v]+", " ", cleaned)
    cleaned = re.sub(r"[ ]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    return cleaned.strip()


def find_first_match(
    patterns: tuple[str, ...],
    text: str,
    flags: int = re.IGNORECASE,
) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=flags)
        if match:
            return normalize_text(match.group(1))
    return ""


def extract_visible_rating(text: str) -> float:
    patterns = (
        r"(?:تقييم|rating)\s*[:|]?\s*(\d(?:[.,]\d+)?)",
        r"(\d(?:[.,]\d+)?)\s*(?:من\s*5|out\s+of\s+5|/5)",
        r"(?:⭐|★|☆)\s*(\d(?:[.,]\d+)?)",
    )
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            rating = safe_rating(match)
            if 1.0 <= rating <= 5.0:
                return rating
    return 0.0


def extract_visible_review_count(text: str) -> int:
    patterns = (
        r"(?:تقييمات\s*العملاء|التقييمات|reviews?|ratings?)\s*[\(\[]?\s*(\d+)",
        r"(\d+)\s*(?:تقييمات|مراجعات|reviews?|ratings?)",
    )
    values: list[int] = []
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            value = safe_int(match)
            if value > 0:
                values.append(value)
    return max(values) if values else 0


def extract_visible_sales_count(text: str) -> int:
    patterns = (
        r"(\d+)\s*(?:مباع|تم\s*بيعه|sold)",
        r"(?:مبيعات|sales?)\s*[:|]?\s*(\d+)",
    )
    values: list[int] = []
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            value = safe_int(match)
            if value > 0:
                values.append(value)
    return max(values) if values else 0


def extract_visible_sizes(text: str) -> list[str]:
    candidates: list[str] = []

    # Explicit size area values.
    size_patterns = (
        r"(?:المقاس|مقاس|size)\s*[:：]?\s*([^\n]{1,120})",
        r"(ONE\s+SIZE)",
    )
    for pattern in size_patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            candidates.extend(re.split(r"[,/|،\s]+", normalize_text(match)))

    # Standard apparel sizes anywhere in rendered DOM.
    candidates.extend(
        re.findall(
            r"(?<![A-Za-z0-9])(?:XXXS|XXS|XS|S|M|L|XL|XXL|XXXL|4XL|5XL|6XL)(?![A-Za-z0-9])",
            text,
            flags=re.IGNORECASE,
        )
    )

    normalized: list[str] = []
    for item in candidates:
        item = normalize_text(item).upper()
        if item == "ONE":
            continue
        if item in {
            "XXXS", "XXS", "XS", "S", "M", "L",
            "XL", "XXL", "XXXL", "4XL", "5XL", "6XL",
            "ONE SIZE",
        }:
            normalized.append(item)

    return unique_strings(normalized, 20)


def extract_visible_colors(text: str) -> list[str]:
    patterns = (
        r"(?:اللون|لون|color|colour)\s*[:：]?\s*([^\n]{1,100})",
    )
    candidates: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            value = normalize_text(match)
            # Stop at likely next UI label.
            value = re.split(
                r"(?:المقاس|مقاس|size|السعر|price|الشحن|shipping)",
                value,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            candidates.extend(re.split(r"[,/|،]+", value))

    blocked = {
        "color", "colour", "لون", "اللون",
        "default", "افتراضي", "اختيار", "select",
    }
    cleaned = []
    for item in candidates:
        item = normalize_text(item)
        if 1 <= len(item) <= 60 and item.casefold() not in blocked:
            cleaned.append(item)
    return unique_strings(cleaned, 20)


def extract_visible_specifications(text: str) -> dict[str, str]:
    """Extract label/value pairs from AliExpress rendered specification text."""
    specs: dict[str, str] = {}
    lines = [normalize_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    heading_indexes = [
        i for i, line in enumerate(lines)
        if line.casefold() in {"المواصفات", "specifications", "specification"}
    ]
    if not heading_indexes:
        return specs

    start = heading_indexes[0] + 1
    end = min(len(lines), start + 120)
    section = lines[start:end]

    stop_terms = {
        "نظرة عامة", "overview", "تقييمات العملاء",
        "customer reviews", "ربما تحب أيضًا", "you may also like",
        "أسئلة وأجابات المشتري", "buyer questions and answers",
    }

    filtered: list[str] = []
    for line in section:
        if line.casefold() in {term.casefold() for term in stop_terms}:
            break
        if line in {"عرض المزيد", "Show more", "show more"}:
            continue
        if len(line) > 180:
            continue
        filtered.append(line)

    # AliExpress often renders alternating label/value cells.
    for i in range(0, len(filtered) - 1, 2):
        left = filtered[i]
        right = filtered[i + 1]
        if (
            left and right
            and left.casefold() != right.casefold()
            and len(left) <= 100
            and len(right) <= 180
        ):
            specs.setdefault(left, right)

    return specs


def extract_visible_reviews(text: str) -> list[str]:
    reviews: list[str] = []
    patterns = (
        r"(?:وفقًا للوصف|as described|very good|good quality|excellent)[^\n]{0,300}",
    )
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            value = normalize_text(match)
            if len(value) >= 8:
                reviews.append(value)
    return unique_strings(reviews, MAX_REVIEWS)



# =========================================================
# ALIEXPRESS DEEP SOURCE EXTRACTION
# =========================================================

def decode_source_text(value: str) -> str:
    """Decode common escaping used in inline AliExpress state objects."""
    decoded = unescape(value)
    replacements = {
        r"\/": "/",
        r"\u002F": "/",
        r"\u002f": "/",
        r"\u003A": ":",
        r"\u003a": ":",
        r"\u0026": "&",
        r"\u003D": "=",
        r"\u003d": "=",
        r"\u0022": '"',
        r"\u0027": "'",
        r"\x2F": "/",
    }
    for old, new in replacements.items():
        decoded = decoded.replace(old, new)
    return decoded


def recursive_decode_json_strings(
    value: Any,
    depth: int = 0,
) -> Any:
    """Decode JSON strings that themselves contain JSON objects or arrays."""
    if depth > 5:
        return value

    if isinstance(value, dict):
        return {
            key: recursive_decode_json_strings(child, depth + 1)
            for key, child in value.items()
        }

    if isinstance(value, list):
        return [
            recursive_decode_json_strings(child, depth + 1)
            for child in value
        ]

    if isinstance(value, str):
        candidate = decode_source_text(value).strip()

        if (
            len(candidate) >= 2
            and candidate[0] in "[{"
            and candidate[-1] in "]}"
        ):
            try:
                parsed = json.loads(candidate)
                return recursive_decode_json_strings(
                    parsed,
                    depth + 1,
                )
            except json.JSONDecodeError:
                return candidate

        return candidate

    return value


def extract_json_ld_blobs(html: str) -> list[Any]:
    blobs: list[Any] = []

    pattern = re.compile(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>'
        r'(.*?)</script>',
        flags=re.IGNORECASE | re.DOTALL,
    )

    for match in pattern.finditer(html):
        parsed = parse_json_text(
            decode_source_text(match.group(1))
        )

        if parsed is not None:
            blobs.append(
                recursive_decode_json_strings(parsed)
            )

    return blobs


def extract_marker_json_blobs(html: str) -> list[Any]:
    """
    Scan the whole source around common AliExpress state/module markers.
    This catches objects embedded outside straightforward JSON script tags.
    """
    decoded_html = decode_source_text(html)
    blobs: list[Any] = []
    seen: set[str] = set()

    markers = (
        "window.runParams",
        "runParams",
        "__INITIAL_STATE__",
        "__PRELOADED_STATE__",
        "__APOLLO_STATE__",
        "pageData",
        "productInfoComponent",
        "productPropComponent",
        "productSkuComponent",
        "skuModule",
        "skuPropertyList",
        "skuPropertyValues",
        "productReview",
        "feedbackComponent",
        "titleModule",
        "imageModule",
        "specificationModule",
        "productDetail",
        "productData",
        "dataLayer",
    )

    for marker_name in markers:
        start_search = 0

        while True:
            marker_index = decoded_html.find(
                marker_name,
                start_search,
            )

            if marker_index == -1:
                break

            search_end = min(
                len(decoded_html),
                marker_index + 1_500_000,
            )

            brace_positions = [
                pos
                for pos in (
                    decoded_html.find("{", marker_index, search_end),
                    decoded_html.find("[", marker_index, search_end),
                )
                if pos != -1
            ]

            if brace_positions:
                start = min(brace_positions)
                candidate = balanced_json_slice(
                    decoded_html,
                    start,
                )

                if candidate:
                    signature = (
                        candidate[:250]
                        + str(len(candidate))
                    )

                    if signature not in seen:
                        parsed = parse_json_text(candidate)

                        if parsed is not None:
                            parsed = recursive_decode_json_strings(
                                parsed
                            )
                            seen.add(signature)
                            blobs.append(parsed)

                            if len(blobs) >= 150:
                                return blobs

            start_search = marker_index + len(marker_name)

    return blobs


def extract_all_json_blobs(html: str) -> list[Any]:
    combined = (
        extract_json_blobs(html)
        + extract_json_ld_blobs(html)
        + extract_marker_json_blobs(html)
    )

    result: list[Any] = []
    signatures: set[str] = set()

    for blob in combined:
        try:
            signature = json.dumps(
                blob,
                ensure_ascii=False,
                sort_keys=True,
            )[:1000]
        except (TypeError, ValueError):
            signature = repr(blob)[:1000]

        if signature in signatures:
            continue

        signatures.add(signature)
        result.append(blob)

    return result


def raw_source_matches(
    html: str,
    patterns: tuple[str, ...],
) -> list[str]:
    source = decode_source_text(html)
    values: list[str] = []

    for pattern in patterns:
        matches = re.findall(
            pattern,
            source,
            flags=re.IGNORECASE | re.DOTALL,
        )

        for match in matches:
            if isinstance(match, tuple):
                match = next(
                    (
                        item
                        for item in match
                        if item
                    ),
                    "",
                )

            value = normalize_text(match)

            if value:
                values.append(value)

    return unique_strings(values)


def extract_raw_rating(html: str) -> float:
    values = raw_source_matches(
        html,
        (
            r'"ratingValue"\s*:\s*"?(\d+(?:\.\d+)?)',
            r'"averageStar"\s*:\s*"?(\d+(?:\.\d+)?)',
            r'"averageRating"\s*:\s*"?(\d+(?:\.\d+)?)',
            r'"evaluationAverage"\s*:\s*"?(\d+(?:\.\d+)?)',
            r'"star"\s*:\s*"?(\d+(?:\.\d+)?)',
            r'"rating"\s*:\s*"?(\d+(?:\.\d+)?)',
            r'(\d+(?:\.\d+)?)\s*(?:out\s+of\s+5|/5)',
        ),
    )

    ratings = [
        safe_rating(value)
        for value in values
        if 1.0 <= safe_rating(value) <= 5.0
    ]

    return max(ratings) if ratings else 0.0


def extract_raw_review_count(html: str) -> int:
    values = raw_source_matches(
        html,
        (
            r'"reviewCount"\s*:\s*"?(\d+)',
            r'"feedbackCount"\s*:\s*"?(\d+)',
            r'"evaluationCount"\s*:\s*"?(\d+)',
            r'"totalReviews"\s*:\s*"?(\d+)',
            r'"totalReviewCount"\s*:\s*"?(\d+)',
            r'(\d+)\s*(?:reviews?|ratings?|تقييمات|مراجعات)',
        ),
    )

    counts = [
        safe_int(value)
        for value in values
        if safe_int(value) > 0
    ]

    return max(counts) if counts else 0


def extract_raw_sales_count(html: str) -> int:
    values = raw_source_matches(
        html,
        (
            r'"tradeCount"\s*:\s*"?(\d+)',
            r'"formatTradeCount"\s*:\s*"[^"\d]*(\d+)',
            r'"orders"\s*:\s*"?(\d+)',
            r'"soldCount"\s*:\s*"?(\d+)',
            r'(\d+)\s*(?:sold|مباع|تم\s*بيعه)',
        ),
    )

    counts = [
        safe_int(value)
        for value in values
        if safe_int(value) > 0
    ]

    return max(counts) if counts else 0


def extract_raw_option_groups(
    html: str,
) -> dict[str, list[str]]:
    """
    Extract SKU option groups directly from escaped or unescaped source.
    """
    source = decode_source_text(html)
    groups: dict[str, list[str]] = {}

    group_pattern = re.compile(
        r'"(?:skuPropertyName|propertyName|propName|attributeName)"'
        r'\s*:\s*"([^"]+)"'
        r'.{0,25000}?'
        r'"(?:skuPropertyValues|propertyValues|values|options)"'
        r'\s*:\s*(\[[\s\S]*?\])',
        flags=re.IGNORECASE,
    )

    for match in group_pattern.finditer(source):
        group_name = normalize_text(match.group(1))
        raw_list = match.group(2)
        parsed = parse_json_text(raw_list)
        values: list[str] = []

        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, str):
                    values.append(item)
                    continue

                if not isinstance(item, dict):
                    continue

                for key in OPTION_VALUE_KEYS:
                    if key in item:
                        values.append(item.get(key))
                        break

        if group_name and values:
            groups.setdefault(group_name, [])
            groups[group_name] = unique_strings(
                groups[group_name] + values,
                50,
            )

    # Independent fallback for common AliExpress SKU display-name fields.
    fallback_values = raw_source_matches(
        source,
        (
            r'"(?:propertyValueDisplayName|skuPropertyValueDisplayName|'
            r'propertyValueName|displayName)"\s*:\s*"([^"]+)"',
        ),
    )

    if fallback_values and not groups:
        size_values = [
            value.upper()
            for value in fallback_values
            if value.upper() in {
                "XXXS", "XXS", "XS", "S", "M", "L",
                "XL", "XXL", "XXXL", "4XL", "5XL", "6XL",
                "ONE SIZE",
            }
        ]
        other_values = [
            value
            for value in fallback_values
            if value.upper() not in set(size_values)
            and len(value) <= 80
        ]

        if size_values:
            groups["Size"] = unique_strings(size_values)

        if other_values:
            groups["Color"] = unique_strings(
                other_values,
                30,
            )

    return groups


def extract_raw_specs(html: str) -> dict[str, str]:
    source = decode_source_text(html)
    specs: dict[str, str] = {}

    pair_patterns = (
        (
            r'"(?:attrName|attributeName|propName|propertyName|specName|'
            r'key|label)"\s*:\s*"([^"]+)"'
            r'.{0,1500}?'
            r'"(?:attrValue|attributeValue|propValue|propertyValue|'
            r'specValue|value|text)"\s*:\s*"([^"]+)"'
        ),
        (
            r'"(?:name|title)"\s*:\s*"([^"]+)"'
            r'.{0,800}?'
            r'"(?:value|text)"\s*:\s*"([^"]+)"'
        ),
    )

    for pattern in pair_patterns:
        for key, value in re.findall(
            pattern,
            source,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            key_text = normalize_text(key)
            value_text = normalize_text(value)

            if (
                key_text
                and value_text
                and key_text.casefold() != value_text.casefold()
                and len(key_text) <= 100
                and len(value_text) <= 500
            ):
                specs.setdefault(key_text, value_text)

            if len(specs) >= MAX_SPECS:
                return specs

    return specs


def extract_raw_reviews(html: str) -> list[str]:
    values = raw_source_matches(
        html,
        (
            r'"(?:buyerFeedback|feedbackContent|reviewContent|'
            r'evaluationContent|comment|content)"\s*:\s*"([^"]{10,1500})"',
        ),
    )

    blocked_terms = (
        "javascript",
        "stylesheet",
        "alicdn",
        "http://",
        "https://",
    )

    reviews = [
        value
        for value in values
        if not any(
            term in value.lower()
            for term in blocked_terms
        )
    ]

    return unique_strings(reviews, MAX_REVIEWS)


def merge_option_groups(
    *group_sets: dict[str, list[str]],
) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}

    for groups in group_sets:
        for key, values in groups.items():
            clean_key = normalize_text(key)

            if not clean_key:
                continue

            merged.setdefault(clean_key, [])
            merged[clean_key] = unique_strings(
                merged[clean_key] + values,
                50,
            )

    return merged


# =========================================================
# ORIGINAL PRODUCT EXTRACTION
# =========================================================

TITLE_KEYS = {
    "subject",
    "producttitle",
    "product_title",
    "itemtitle",
    "item_title",
    "title",
    "name",
}

RATING_KEYS = {
    "ratingvalue",
    "rating_value",
    "averagestar",
    "average_star",
    "averageRating",
    "evaluationaverage",
    "evaluation_average",
    "star",
    "stars",
    "rating",
}

REVIEW_COUNT_KEYS = {
    "reviewcount",
    "review_count",
    "feedbackcount",
    "feedback_count",
    "evaluationcount",
    "evaluation_count",
    "totalreviews",
    "total_reviews",
}

IMAGE_KEY_MARKERS = (
    "image",
    "img",
    "pic",
    "photo",
)

VIDEO_KEY_MARKERS = (
    "video",
    "mediaurl",
    "media_url",
)

SPEC_NAME_KEYS = (
    "attrname",
    "attributename",
    "propname",
    "propertyname",
    "specname",
    "skuPropertyName",
    "name",
    "key",
    "label",
)

SPEC_VALUE_KEYS = (
    "attrvalue",
    "attributevalue",
    "propvalue",
    "propertyvalue",
    "specvalue",
    "value",
    "text",
)

OPTION_GROUP_KEYS = (
    "skuPropertyName",
    "propertyName",
    "propName",
    "attributeName",
    "name",
)

OPTION_VALUE_KEYS = (
    "propertyValueDisplayName",
    "skuPropertyValueDisplayName",
    "propertyValueName",
    "displayName",
    "value",
    "name",
)


def extract_original_name(
    html: str,
    walked: list[tuple[tuple[str, ...], Any]],
) -> str:
    meta_title = extract_title_from_html(html)

    candidates: list[str] = [meta_title]

    for path, value in walked:
        if not path or not isinstance(value, str):
            continue

        key = path[-1].lower()
        text = normalize_text(value)

        if key not in {item.lower() for item in TITLE_KEYS}:
            continue

        if len(text) < 10 or len(text) > 500:
            continue

        lowered_path = path_text(path)

        if any(
            blocked in lowered_path
            for blocked in (
                "store",
                "seller",
                "category",
                "breadcrumb",
                "review",
                "seo",
            )
        ):
            continue

        candidates.append(text)

    candidates = unique_strings(candidates)

    if not candidates:
        return "Product from supplier link"

    return max(candidates, key=len)[:500]


def extract_images(
    html: str,
    walked: list[tuple[tuple[str, ...], Any]],
) -> list[str]:
    candidates: list[str] = []

    meta_image = extract_meta_content(
        html,
        property_name="og:image",
    )

    if meta_image:
        candidates.append(meta_image)

    url_pattern = re.compile(
        r'(?:https?:)?//[^"\'\s<>\\]+?'
        r'(?:\.jpg|\.jpeg|\.png|\.webp|\.avif)'
        r'(?:\?[^"\'\s<>\\]*)?',
        flags=re.IGNORECASE,
    )

    candidates.extend(url_pattern.findall(html))

    for path, value in walked:
        current_path = path_text(path)

        if not any(marker in current_path for marker in IMAGE_KEY_MARKERS):
            continue

        if isinstance(value, str):
            candidates.append(value)

        elif isinstance(value, list):
            candidates.extend(
                item
                for item in value
                if isinstance(item, str)
            )

    cleaned: list[str] = []

    for candidate in candidates:
        url = clean_url(candidate)

        if url and is_image_url(url):
            cleaned.append(url)

    return unique_strings(cleaned, MAX_IMAGES)


def extract_videos(
    html: str,
    walked: list[tuple[tuple[str, ...], Any]],
) -> list[str]:
    candidates: list[str] = []

    video_pattern = re.compile(
        r'(?:https?:)?//[^"\'\s<>\\]+?'
        r'(?:\.mp4|\.m3u8)'
        r'(?:\?[^"\'\s<>\\]*)?',
        flags=re.IGNORECASE,
    )

    candidates.extend(video_pattern.findall(html))

    for path, value in walked:
        current_path = path_text(path)

        if not any(marker in current_path for marker in VIDEO_KEY_MARKERS):
            continue

        if isinstance(value, str):
            candidates.append(value)

        elif isinstance(value, list):
            candidates.extend(
                item
                for item in value
                if isinstance(item, str)
            )

    cleaned: list[str] = []

    for candidate in candidates:
        url = clean_url(candidate)

        if url and is_video_url(url):
            cleaned.append(url)

    return unique_strings(cleaned, MAX_VIDEOS)


def extract_rating(
    html: str,
    walked: list[tuple[tuple[str, ...], Any]],
) -> float:
    candidates: list[float] = []

    for path, value in walked:
        if not path:
            continue

        key = path[-1].lower()

        if key not in {item.lower() for item in RATING_KEYS}:
            continue

        rating = safe_rating(value)

        if rating > 0:
            candidates.append(rating)

    for pattern in (
        r'"ratingValue"\s*:\s*"?(\d+(?:\.\d+)?)',
        r'"averageStar"\s*:\s*"?(\d+(?:\.\d+)?)',
        r'"evaluationAverage"\s*:\s*"?(\d+(?:\.\d+)?)',
        r'(\d+(?:\.\d+)?)\s*(?:out of 5|/5)',
    ):
        for match in re.findall(pattern, html, flags=re.IGNORECASE):
            rating = safe_rating(match)

            if rating > 0:
                candidates.append(rating)

    if not candidates:
        return 0.0

    realistic = [
        value
        for value in candidates
        if 1.0 <= value <= 5.0
    ]

    return max(realistic) if realistic else 0.0


def extract_review_count(
    html: str,
    walked: list[tuple[tuple[str, ...], Any]],
) -> int:
    candidates: list[int] = []

    for path, value in walked:
        if not path:
            continue

        key = path[-1].lower()

        if key not in {
            item.lower()
            for item in REVIEW_COUNT_KEYS
        }:
            continue

        count = safe_int(value)

        if count > 0:
            candidates.append(count)

    for pattern in (
        r'"reviewCount"\s*:\s*"?(\d+)',
        r'"feedbackCount"\s*:\s*"?(\d+)',
        r'"evaluationCount"\s*:\s*"?(\d+)',
        r'(\d+)\s+(?:reviews?|ratings?)',
    ):
        for match in re.findall(pattern, html, flags=re.IGNORECASE):
            count = safe_int(match)

            if count > 0:
                candidates.append(count)

    return max(candidates) if candidates else 0


def extract_reviews(
    walked: list[tuple[tuple[str, ...], Any]],
) -> list[str]:
    candidates: list[str] = []

    for path, value in walked:
        if not isinstance(value, str):
            continue

        current_path = path_text(path)

        if not any(
            marker in current_path
            for marker in (
                "review",
                "feedback",
                "evaluation",
            )
        ):
            continue

        if not any(
            marker in current_path
            for marker in (
                "content",
                "comment",
                "text",
                "body",
                "buyerfeedback",
            )
        ):
            continue

        text = normalize_text(value)

        if 15 <= len(text) <= 1500:
            candidates.append(text)

    return unique_strings(candidates, MAX_REVIEWS)


def extract_specs_from_dict(
    node: dict[str, Any],
) -> tuple[str, str] | None:
    lowered = {
        str(key).lower(): value
        for key, value in node.items()
    }

    name_value = None
    spec_value = None

    for key in SPEC_NAME_KEYS:
        candidate = lowered.get(key.lower())

        if candidate is not None:
            name_value = candidate
            break

    for key in SPEC_VALUE_KEYS:
        candidate = lowered.get(key.lower())

        if candidate is not None:
            spec_value = candidate
            break

    name = normalize_text(name_value)

    if isinstance(spec_value, list):
        value = ", ".join(unique_strings(spec_value))
    else:
        value = normalize_text(spec_value)

    if (
        name
        and value
        and name.casefold() != value.casefold()
        and len(name) <= 100
        and len(value) <= 500
    ):
        return name, value

    return None


def extract_option_groups(
    walked: list[tuple[tuple[str, ...], Any]],
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}

    for _, value in walked:
        if not isinstance(value, dict):
            continue

        group_name = ""

        for key in OPTION_GROUP_KEYS:
            if key in value:
                group_name = normalize_text(value.get(key))
                break

        if not group_name:
            continue

        values: list[str] = []

        for child_key in (
            "skuPropertyValues",
            "propertyValues",
            "values",
            "options",
        ):
            child = value.get(child_key)

            if not isinstance(child, list):
                continue

            for item in child:
                if isinstance(item, str):
                    values.append(item)
                    continue

                if not isinstance(item, dict):
                    continue

                for value_key in OPTION_VALUE_KEYS:
                    if value_key in item:
                        values.append(item.get(value_key))
                        break

        values = unique_strings(values)

        if values:
            groups.setdefault(group_name, [])
            groups[group_name].extend(values)
            groups[group_name] = unique_strings(
                groups[group_name]
            )

    return groups


def classify_option_groups(
    groups: dict[str, list[str]],
) -> tuple[list[str], list[str]]:
    colors: list[str] = []
    sizes: list[str] = []

    for group_name, values in groups.items():
        lowered = group_name.lower()

        if any(
            marker in lowered
            for marker in (
                "color",
                "colour",
                "لون",
            )
        ):
            colors.extend(values)

        if any(
            marker in lowered
            for marker in (
                "size",
                "مقاس",
            )
        ):
            sizes.extend(values)

    return unique_strings(colors), unique_strings(sizes)


def extract_specs(
    walked: list[tuple[tuple[str, ...], Any]],
    colors: list[str],
    sizes: list[str],
) -> dict[str, str]:
    specs: dict[str, str] = {}

    for _, value in walked:
        if not isinstance(value, dict):
            continue

        pair = extract_specs_from_dict(value)

        if not pair:
            continue

        key, item_value = pair

        if key not in specs:
            specs[key] = item_value

        if len(specs) >= MAX_SPECS:
            break

    if colors:
        specs.setdefault("Colors", ", ".join(colors))

    if sizes:
        specs.setdefault("Sizes", ", ".join(sizes))

    return specs


def extract_named_spec(
    specs: dict[str, str],
    keywords: tuple[str, ...],
) -> str:
    for key, value in specs.items():
        lowered = key.lower()

        if any(keyword in lowered for keyword in keywords):
            return value

    return ""


def extract_original_product(
    html: str,
) -> dict[str, Any]:
    blobs = extract_all_json_blobs(html)
    walked = all_walked(blobs)
    visible_text = html_to_visible_text(html)

    json_option_groups = extract_option_groups(walked)
    raw_option_groups = extract_raw_option_groups(html)
    option_groups = merge_option_groups(
        json_option_groups,
        raw_option_groups,
    )

    json_colors, json_sizes = classify_option_groups(
        option_groups
    )
    visible_colors = extract_visible_colors(visible_text)
    visible_sizes = extract_visible_sizes(visible_text)

    colors = unique_strings(
        json_colors + visible_colors,
        30,
    )
    sizes = unique_strings(
        json_sizes + visible_sizes,
        30,
    )

    specs = extract_specs(walked, colors, sizes)

    raw_specs = extract_raw_specs(html)
    for key, value in raw_specs.items():
        specs.setdefault(key, value)

    visible_specs = extract_visible_specifications(
        visible_text
    )
    for key, value in visible_specs.items():
        specs.setdefault(key, value)

    if colors:
        specs.setdefault("Colors", ", ".join(colors))

    if sizes:
        specs.setdefault("Sizes", ", ".join(sizes))

    rating_candidates = [
        extract_rating(html, walked),
        extract_raw_rating(html),
        extract_visible_rating(visible_text),
    ]
    rating = max(rating_candidates)

    review_count = max(
        extract_review_count(html, walked),
        extract_raw_review_count(html),
        extract_visible_review_count(visible_text),
    )

    sales_count = max(
        extract_raw_sales_count(html),
        extract_visible_sales_count(visible_text),
    )

    reviews = unique_strings(
        extract_reviews(walked)
        + extract_raw_reviews(html)
        + extract_visible_reviews(visible_text),
        MAX_REVIEWS,
    )

    product = {
        "name": extract_original_name(html, walked),
        "specifications": specs,
        "specifications_text": format_specs(specs),
        "colors": colors,
        "sizes": sizes,
        "material": extract_named_spec(
            specs,
            (
                "material",
                "fabric",
                "composition",
                "الخامة",
                "نوع القماش",
            ),
        ),
        "brand": extract_named_spec(
            specs,
            (
                "brand",
                "ماركة",
                "العلامة",
            ),
        ),
        "country_of_origin": extract_named_spec(
            specs,
            (
                "origin",
                "country",
                "place of origin",
                "بلد",
                "المنشأ",
            ),
        ),
        "rating": rating,
        "review_count": review_count,
        "sales_count": sales_count,
        "reviews": reviews,
        "images": extract_images(html, walked),
        "videos": extract_videos(html, walked),
        "option_groups": option_groups,
        "json_blobs_found": len(blobs),
    }

    return product


# =========================================================
# AI CONTENT
# =========================================================

def ai_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
            },
            "description": {
                "type": "string",
            },
            "features": {
                "type": "array",
                "items": {"type": "string"},
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
            "selling_angles": {
                "type": "array",
                "items": {"type": "string"},
            },
            "hooks": {
                "type": "array",
                "items": {"type": "string"},
            },
            "ctas": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "name",
            "description",
            "features",
            "seo_keywords",
            "faqs",
            "selling_angles",
            "hooks",
            "ctas",
        ],
        "additionalProperties": False,
    }


def build_ai_prompt(
    original: dict[str, Any],
) -> str:
    safe_original = {
        "name": original.get("name", ""),
        "specifications": original.get(
            "specifications",
            {},
        ),
        "colors": original.get("colors", []),
        "sizes": original.get("sizes", []),
        "material": original.get("material", ""),
        "brand": original.get("brand", ""),
        "country_of_origin": original.get(
            "country_of_origin",
            "",
        ),
        "rating": original.get("rating", 0),
        "review_count": original.get(
            "review_count",
            0,
        ),
    }

    return f"""
You are ShwayGo Engine AI.

Create premium e-commerce marketing content using ONLY the verified
supplier facts supplied below.

STRICT RULES:
1. Never invent a color, size, material, brand, origin, rating,
   review, image, video, dimension, certification, or product feature.
2. You may rewrite and improve the product name.
3. The description must be persuasive, clear, search-friendly,
   and based only on verified facts.
4. Generate 5 to 8 concise key features.
5. Generate 12 to 20 useful SEO keyword phrases.
6. Generate 5 useful FAQs with factual answers.
7. Generate 3 to 6 selling angles.
8. Generate 5 short advertising hooks.
9. Generate 3 clear calls to action.
10. Return JSON only and follow the schema exactly.
11. If very few supplier facts are available, remain conservative
    and do not fill gaps with assumptions.

VERIFIED ORIGINAL PRODUCT DATA:
{json.dumps(safe_original, ensure_ascii=False)}
""".strip()


def extract_google_error(response_data: Any) -> str:
    if isinstance(response_data, dict):
        error = response_data.get("error")

        if isinstance(error, dict):
            parts = unique_strings(
                [
                    error.get("code"),
                    error.get("status"),
                    error.get("message"),
                ]
            )

            if parts:
                return " | ".join(parts)

        return json.dumps(
            response_data,
            ensure_ascii=False,
        )[:1500]

    return normalize_text(response_data)[:1500]


def extract_interaction_text(
    response_data: dict[str, Any],
) -> str:
    text_parts: list[str] = []

    for step in response_data.get("steps", []):
        if not isinstance(step, dict):
            continue

        if step.get("type") != "model_output":
            continue

        for item in step.get("content", []):
            if not isinstance(item, dict):
                continue

            if item.get("type") == "text":
                text = normalize_text(item.get("text"))

                if text:
                    text_parts.append(text)

    return "\n".join(text_parts).strip()


def parse_json_object(text: str) -> dict[str, Any]:
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
        start = cleaned.find("{")
        end = cleaned.rfind("}")

        if start == -1 or end == -1:
            raise RuntimeError(
                "Gemini response did not contain JSON."
            )

        parsed = json.loads(cleaned[start:end + 1])

    if not isinstance(parsed, dict):
        raise RuntimeError(
            "Gemini output was not a JSON object."
        )

    return parsed


def call_gemini(
    api_key: str,
    original: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    model = (
        os.environ.get(
            "GEMINI_MODEL",
            DEFAULT_GEMINI_MODEL,
        ).strip()
        or DEFAULT_GEMINI_MODEL
    )

    payload = {
        "model": model,
        "input": build_ai_prompt(original),
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": ai_response_schema(),
        },
        "generation_config": {
            "temperature": 0.2,
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
                timeout=REQUEST_TIMEOUT_GEMINI,
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
                        "Gemini returned an invalid object."
                    )

                status = normalize_text(
                    response_data.get("status")
                )

                if status and status != "completed":
                    raise RuntimeError(
                        f"Gemini status was {status}."
                    )

                output_text = extract_interaction_text(
                    response_data
                )

                if not output_text:
                    raise RuntimeError(
                        "Gemini returned no output text."
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
            } and attempt < 3:
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


def normalize_ai_data(
    value: dict[str, Any],
    original_name: str,
) -> dict[str, Any]:
    seo_keywords = unique_strings(
        value.get("seo_keywords", []),
        30,
    )

    if not seo_keywords:
        fallback_terms = unique_strings(
            re.findall(
                r"[A-Za-z0-9][A-Za-z0-9\-]{2,}",
                original_name,
            ),
            12,
        )
        seo_keywords = fallback_terms

    return {
        "name": (
            normalize_text(value.get("name"))
            or original_name
        ),
        "description": normalize_text(
            value.get("description")
        ),
        "key_features": unique_strings(
            value.get("features", []),
            10,
        ),
        "seo_keywords": seo_keywords,
        "faqs": (
            value.get("faqs")
            if isinstance(value.get("faqs"), list)
            else []
        ),
        "selling_angles": unique_strings(
            value.get("selling_angles", []),
            10,
        ),
        "hooks": unique_strings(
            value.get("hooks", []),
            10,
        ),
        "ctas": unique_strings(
            value.get("ctas", []),
            10,
        ),
    }


def fallback_ai_data(
    original: dict[str, Any],
) -> dict[str, Any]:
    name = normalize_text(original.get("name"))

    return {
        "name": name,
        "description": "",
        "key_features": [],
        "seo_keywords": unique_strings(
            re.findall(
                r"[A-Za-z0-9][A-Za-z0-9\-]{2,}",
                name,
            ),
            12,
        ),
        "faqs": [],
        "selling_angles": [],
        "hooks": [],
        "ctas": [],
    }


# =========================================================
# SCRAPINGANT
# =========================================================

def build_scrapingant_js_snippet() -> str:
    """Return Base64-encoded JavaScript for interactive page loading."""
    script = r"""
(async () => {
  const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
  const labels = [
    "show more", "see more", "view more", "more details",
    "specifications", "product details", "customer reviews",
    "reviews", "buyer questions", "questions & answers",
    "عرض المزيد", "المزيد", "المواصفات", "تفاصيل المنتج",
    "تقييمات العملاء", "التقييمات", "المراجعات",
    "أسئلة وأجابات المشتري", "أسئلة وأجوبة المشتري"
  ];
  const blocked = [
    "buy now", "add to cart", "checkout", "purchase",
    "اشتري الآن", "أضف إلى السلة", "الدفع"
  ];
  const textOf = (el) => ((el.innerText || el.textContent || "")
    .replace(/\s+/g, " ").trim().toLowerCase());
  const clickInfo = async () => {
    const items = Array.from(document.querySelectorAll(
      "button,[role='button'],a,summary,[aria-expanded='false']"
    ));
    for (const el of items) {
      const text = textOf(el);
      if (!text || text.length > 160) continue;
      if (blocked.some(x => text.includes(x))) continue;
      if (!labels.some(x => text.includes(x))) continue;
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      if (r.width < 2 || r.height < 2 || s.display === "none" || s.visibility === "hidden") continue;
      try {
        el.scrollIntoView({block:"center",behavior:"auto"});
        el.click();
        await sleep(450);
      } catch (_) {}
    }
  };
  await sleep(2500);
  let h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
  for (let i = 0; i <= 12; i++) {
    scrollTo(0, Math.floor(h * i / 12));
    await sleep(650);
    if ([3,7,10].includes(i)) await clickInfo();
  }
  await clickInfo();
  await sleep(1800);
  h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
  for (let i = 0; i <= 8; i++) {
    scrollTo(0, Math.floor(h * i / 8));
    await sleep(500);
  }
  await clickInfo();
  await sleep(1800);
  scrollTo(0, 0);
  await sleep(500);
  return {title: document.title, height: h, textLength: document.body ? document.body.innerText.length : 0};
})();
""".strip()
    return base64.b64encode(script.encode('utf-8')).decode('ascii')


def fetch_supplier_html(
    product_url: str,
    scrapingant_key: str,
) -> str:
    endpoint = "https://api.scrapingant.com/v2/general"
    response = requests.get(
        endpoint,
        params={
            "url": product_url,
            "x-api-key": scrapingant_key,
            "browser": "true",
            "wait_for_selector": "body",
            "js_snippet": build_scrapingant_js_snippet(),
        },
        timeout=REQUEST_TIMEOUT_SCRAPER,
    )

    if response.status_code != 200:
        print(
            "SCRAPINGANT ADVANCED REQUEST FAILED:",
            response.status_code,
            response.text[:700],
        )
        response = requests.get(
            endpoint,
            params={
                "url": product_url,
                "x-api-key": scrapingant_key,
                "browser": "true",
            },
            timeout=REQUEST_TIMEOUT_SCRAPER,
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
    service_error_terms = (
        "zenrows web scraping api",
        "trial expired",
        "auth005",
        "missing api token",
        "invalid api token",
        "subscription expired",
        "payment required",
    )

    if any(term in lowered for term in service_error_terms):
        raise RuntimeError(
            "The scraper returned a service error page."
        )

    debug_html = (
        os.environ.get("DEBUG_HTML", "false")
        .strip()
        .lower()
        in {"1", "true", "yes"}
    )

    if debug_html:
        print("HTML LENGTH:", len(html))
        print(
            "HTML CHECKS:",
            {
                "has_rating_word": "rating" in lowered,
                "has_reviews_word": (
                    "review" in lowered
                    or "feedback" in lowered
                ),
                "has_sku_word": "sku" in lowered,
                "has_size_word": "size" in lowered,
                "has_color_word": (
                    "color" in lowered
                    or "colour" in lowered
                ),
                "has_arabic_specs": "المواصفات" in html,
                "has_arabic_reviews": "تقييمات العملاء" in html,
            },
        )
        print("HTML START:", html[:3000])

    return html


# =========================================================
# RESPONSE BUILDERS
# =========================================================

def compatibility_fields(
    original: dict[str, Any],
    ai: dict[str, Any],
) -> dict[str, Any]:
    return {
        "names": normalize_text(original.get("name")),
        "description": normalize_text(ai.get("description")),
        "key_features": join_lines(
            ai.get("key_features", [])
        ),
        "specifications": normalize_text(
            original.get("specifications_text")
        ),
        "seo_keywords": ", ".join(
            unique_strings(ai.get("seo_keywords", []))
        ),
        "faqs": format_faqs(ai.get("faqs", [])),
        "reviews_text": join_lines(
            original.get("reviews", [])
        ),
        "product_rating": safe_rating(
            original.get("rating")
        ),
        "images": (
            original.get("images")
            if isinstance(original.get("images"), list)
            else []
        ),
        "videos_link": join_lines(
            original.get("videos", [])
        ),
    }


def success_response(
    product_url: str,
    original: dict[str, Any],
    ai: dict[str, Any],
    source: str,
    **extra: Any,
) -> dict[str, Any]:
    legacy = compatibility_fields(original, ai)

    response = {
        "status": "success",
        "source": source,
        "product_url": product_url,

        # Current FlutterFlow compatibility.
        **legacy,
        "data": legacy,

        # New clean separation.
        "original": {
            "name": normalize_text(
                original.get("name")
            ),
            "specifications": (
                original.get("specifications")
                if isinstance(
                    original.get("specifications"),
                    dict,
                )
                else {}
            ),
            "specifications_text": normalize_text(
                original.get("specifications_text")
            ),
            "colors": (
                original.get("colors")
                if isinstance(original.get("colors"), list)
                else []
            ),
            "sizes": (
                original.get("sizes")
                if isinstance(original.get("sizes"), list)
                else []
            ),
            "material": normalize_text(
                original.get("material")
            ),
            "brand": normalize_text(
                original.get("brand")
            ),
            "country_of_origin": normalize_text(
                original.get("country_of_origin")
            ),
            "rating": safe_rating(
                original.get("rating")
            ),
            "review_count": safe_int(
                original.get("review_count")
            ),
            "sales_count": safe_int(
                original.get("sales_count")
            ),
            "reviews": (
                original.get("reviews")
                if isinstance(original.get("reviews"), list)
                else []
            ),
            "images": (
                original.get("images")
                if isinstance(original.get("images"), list)
                else []
            ),
            "videos": (
                original.get("videos")
                if isinstance(original.get("videos"), list)
                else []
            ),
            "option_groups": (
                original.get("option_groups")
                if isinstance(
                    original.get("option_groups"),
                    dict,
                )
                else {}
            ),
        },
        "ai": {
            "name": normalize_text(ai.get("name")),
            "description": normalize_text(
                ai.get("description")
            ),
            "key_features": (
                ai.get("key_features")
                if isinstance(ai.get("key_features"), list)
                else []
            ),
            "seo_keywords": (
                ai.get("seo_keywords")
                if isinstance(ai.get("seo_keywords"), list)
                else []
            ),
            "faqs": (
                ai.get("faqs")
                if isinstance(ai.get("faqs"), list)
                else []
            ),
            "selling_angles": (
                ai.get("selling_angles")
                if isinstance(ai.get("selling_angles"), list)
                else []
            ),
            "hooks": (
                ai.get("hooks")
                if isinstance(ai.get("hooks"), list)
                else []
            ),
            "ctas": (
                ai.get("ctas")
                if isinstance(ai.get("ctas"), list)
                else []
            ),
        },
    }

    response.update(extra)
    return response


def error_response(
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    response = {
        "status": "error",
        "message": message,
    }
    response.update(extra)
    return response


# =========================================================
# ROUTES
# =========================================================

@app.get("/")
def health_check() -> dict[str, Any]:
    model = (
        os.environ.get(
            "GEMINI_MODEL",
            DEFAULT_GEMINI_MODEL,
        ).strip()
        or DEFAULT_GEMINI_MODEL
    )

    return {
        "status": "ok",
        "service": "ShwayGo Engine API",
        "version": "4.3.0",
        "architecture": "original_plus_ai",
        "collection_mode": "scrapingant_interactive_browser",
        "gemini_api": "interactions_v1beta",
        "gemini_model": model,
    }


@app.post("/scrape")
def scrape(request: ScrapeRequest) -> dict[str, Any]:
    started_at = time.time()
    product_url = str(request.url)

    scrapingant_key = os.environ.get(
        "SCRAPINGANT_API_KEY",
        "",
    ).strip()

    gemini_key = os.environ.get(
        "GEMINI_API_KEY",
        "",
    ).strip()

    configured_model = (
        os.environ.get(
            "GEMINI_MODEL",
            DEFAULT_GEMINI_MODEL,
        ).strip()
        or DEFAULT_GEMINI_MODEL
    )

    if not scrapingant_key:
        return error_response(
            "Missing SCRAPINGANT_API_KEY."
        )

    try:
        html = fetch_supplier_html(
            product_url,
            scrapingant_key,
        )
    except Exception as exc:
        return error_response(
            "Supplier page extraction failed.",
            details=str(exc)[:1500],
            elapsed_seconds=round(
                time.time() - started_at,
                2,
            ),
        )

    try:
        original = extract_original_product(html)
    except Exception as exc:
        return error_response(
            "Original product parsing failed.",
            details=str(exc)[:1500],
            elapsed_seconds=round(
                time.time() - started_at,
                2,
            ),
        )

    if not gemini_key:
        ai = fallback_ai_data(original)

        return success_response(
            product_url=product_url,
            original=original,
            ai=ai,
            source="original_only_no_gemini_key",
            gemini_model=configured_model,
            elapsed_seconds=round(
                time.time() - started_at,
                2,
            ),
        )

    try:
        raw_ai, model_used = call_gemini(
            gemini_key,
            original,
        )
        ai = normalize_ai_data(
            raw_ai,
            normalize_text(original.get("name")),
        )

        return success_response(
            product_url=product_url,
            original=original,
            ai=ai,
            source="original_plus_gemini",
            gemini_model=model_used,
            gemini_api="interactions_v1beta",
            original_json_blobs_found=safe_int(
                original.get("json_blobs_found")
            ),
            elapsed_seconds=round(
                time.time() - started_at,
                2,
            ),
        )

    except Exception as exc:
        ai = fallback_ai_data(original)

        return success_response(
            product_url=product_url,
            original=original,
            ai=ai,
            source="original_plus_ai_fallback",
            gemini_model=configured_model,
            gemini_api="interactions_v1beta",
            gemini_error=str(exc)[:1500],
            original_json_blobs_found=safe_int(
                original.get("json_blobs_found")
            ),
            elapsed_seconds=round(
                time.time() - started_at,
                2,
            ),
        )
