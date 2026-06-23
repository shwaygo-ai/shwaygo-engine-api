import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import google.generativeai as genai

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# هنا نستخدم النسخة والموديل الذي ثبتّ نجاحه معك سابقاً
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
# لا تغير اسم الموديل، استخدم الاسم الذي كان يعمل معك سابقاً
model = genai.GenerativeModel('gemini-1.5-flash') 

class ScrapeRequest(BaseModel):
    url: str

@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    zenrows_key = os.environ.get("ZENROWS_API_KEY")
    zenrows_url = f"https://api.zenrows.com/v1/?apikey={zenrows_key}&url={request.url}&js_render=true"
    
    response = requests.get(zenrows_url)
    # استخدمنا النسخة التي نجحت معك
    prompt = f"استخرج البيانات التالية وصغ وصفاً تسويقياً: {response.text[:20000]}"
    ai_response = model.generate_content(prompt)
    
    return {
        "status": "success",
        "ai_content": ai_response.text
    }
