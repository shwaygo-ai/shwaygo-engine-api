@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    try:
        gemini_key = os.environ.get("GEMINI_API_KEY")
        zenrows_key = os.environ.get("ZENROWS_API_KEY")

        if not gemini_key or not zenrows_key:
            return {"status": "error", "message": "المفاتيح غير موجودة"}

        # 1. سحب البيانات الخام (ZenRows)
        zenrows_params = {"apikey": zenrows_key, "url": request.url, "js_render": "true"}
        response = requests.get("https://api.zenrows.com/v1/", params=zenrows_params)
        
        if response.status_code != 200:
            return {"status": "error", "message": "فشل السحب"}

        # 2. الأمر الذكي (Prompt) - لاحظ أننا ضاعفنا الأقواس {{ }}
        prompt = f"""
        أنت الآن خبير تجارة إلكترونية. حلل بيانات المنتج التالية.
        استخرج "جميع" روابط الصور الموجودة في معرض صور المنتج (Image Gallery)، ولا تكتفِ بالصورة الرئيسية.
        يجب أن يكون ردك "فقط" كود JSON بالتنسيق التالي:
        {{"name": "", "images": ["رابط1", "رابط2", ...], "videos": [], "description": "", "features": [], "specifications": {{}}, "seo_assets": "", "faq_assets": [], "reviews_assets": [], "rating": "", "back_reviews": ""}}
        بيانات المنتج الخام: {response.text[:15000]}
        """
        
        # 3. الاتصال المباشر بـ Gemini 3.5 Flash
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={gemini_key}"
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        gemini_response = requests.post(gemini_url, headers=headers, json=payload)
        
        if gemini_response.status_code != 200:
            return {"status": "error", "message": "خطأ من جوجل"}

        # 4. تنظيف ومعالجة النتيجة (JSON)
        ai_text = gemini_response.json()["candidates"][0]["content"]["parts"][0]["text"]
        ai_text = ai_text.replace("```json", "").replace("```", "").strip()
        
        data = json.loads(ai_text)
        return {"status": "success", "data": data}

    except Exception as e:
        return {"status": "error", "message": str(e)}
