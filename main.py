Import os

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



if not gemini_key or not zenrows_key:

return {"status": "error", "message": "المفاتيح مفقودة"}



# 1. سحب البيانات عبر ZenRows

zenrows_params = {"apikey": zenrows_key, "url": request.url, "js_render": "true"}

response = requests.get("https://api.zenrows.com/v1/", params=zenrows_params)


if response.status_code != 200:

return {"status": "error", "message": f"خطأ في السحب: {response.status_code}"}



# 2. إعداد الطلب (Prompt) بصرامة عالية

prompt = f"""

استخرج بيانات المنتج التالية وأكمل أي نقص بذكاء.

يجب أن يكون ردك "فقط" كود JSON ولا شيء غيره، بالتنسيق التالي:

{{"name": "", "images": [], "videos": [], "description": "", "features": [], "specifications": {}, "seo_assets": "", "faq_assets": [], "reviews_assets": [], "rating": "", "back_reviews": ""}}

بيانات المنتج الخام: {response.text[:15000]}

"""


# 3. الاتصال المباشر بـ gemini-3.5-flash

gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={gemini_key}"

headers = {"Content-Type": "application/json"}

payload = {"contents": [{"parts": [{"text": prompt}]}]}


gemini_response = requests.post(gemini_url, headers=headers, json=payload)


if gemini_response.status_code != 200:

return {"status": "error", "message": f"خطأ جوجل: {gemini_response.status_code}"}



# 4. معالجة آمنة للبيانات

ai_text = gemini_response.json()["candidates"][0]["content"]["parts"][0]["text"]

ai_text = ai_text.replace("```json", "").replace("```", "").strip()


try:

data = json.loads(ai_text)

return {"status": "success", "data": data}

except json.JSONDecodeError:

return {"status": "error", "message": "الذكاء الاصطناعي لم يرجع JSON صالح", "raw_output": ai_text}



except Exception as e:

return {"status": "error", "message": f"خطأ برمجي: {str(e)}"}
