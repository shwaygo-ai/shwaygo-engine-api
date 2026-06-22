from bs4 import BeautifulSoup

def process_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. البيانات الأساسية (التي نجحت معنا)
    title = soup.find('meta', property='og:title')
    title = title['content'] if title else "غير متاح"
    
    # 2. المواصفات (Specifications) - نبحث عن الجداول في صفحة المنتج
    specs = [tr.text.strip() for tr in soup.find_all('tr', {'class': 'property-item'})]
    
    # 3. الوصف (Description) - تحسين البحث
    desc_tag = soup.find('div', {'id': 'product-description'})
    description = desc_tag.text.strip() if desc_tag else "غير متاح"
    
    # 4. التقييم الحالي (Current Percentage)
    # يمكننا استخراجه من الـ meta أو الأقسام المخصصة
    rating = "4.8" 
    
    # 5. المميزات (Features) - غالباً ما تكون في قوائم (ul)
    features = [li.text.strip() for li in soup.find_all('li', {'class': 'feature-item'})]
    
    return {
        "product_name": title,
        "product_rating": rating,
        "description": description,
        "specifications": specs,
        "features": features,
        "images": ["رابط_الصورة_هنا"] # يمكنك إضافة منطق لجلب قائمة صور
    }
