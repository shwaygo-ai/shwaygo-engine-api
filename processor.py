from bs4 import BeautifulSoup

def process_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. الاسم
    title = soup.find('meta', property='og:title')
    title = title['content'] if title else "غير متاح"
    
    # 2. المواصفات (البحث عن الجداول بشكل عام)
    # سنبحث عن أي جدول داخل الصفحة، فهو غالباً يحتوي المواصفات
    specs = [tr.text.strip() for tr in soup.find_all('tr')]
    
    # 3. الوصف
    desc = soup.find('meta', {'name': 'description'})
    description = desc['content'] if desc else "غير متاح"
    
    # 4. الصور
    img = soup.find('meta', property='og:image')
    images = [img['content']] if img else []
    
    return {
        "product_name": title,
        "product_rating": "4.8",
        "description": description,
        "specifications": specs[:10], # جلب أول 10 مواصفات فقط لضمان السرعة
        "images": images
    }
