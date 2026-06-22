from bs4 import BeautifulSoup

def process_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # استخراج الاسم
    title_tag = soup.find('meta', property='og:title')
    title = title_tag['content'] if title_tag else "لم يتم العثور على الاسم"
    
    # استخراج التقييم (نبحث عن أكثر من كلاس محتمل)
    rating_tag = soup.find('span', {'class': 'overview-rating-average'}) or soup.find('span', {'class': 'rating-value'})
    rating = rating_tag.text.strip() if rating_tag else "غير متوفر"
    
    # استخراج الوصف (نبحث عن الـ meta description كخيار مضمون)
    desc_tag = soup.find('meta', {'name': 'description'}) or soup.find('div', {'id': 'product-description'})
    description = desc_tag.get('content', '') if desc_tag and desc_tag.name == 'meta' else (desc_tag.text.strip() if desc_tag else "غير متوفر")
    
    # استخراج الصور (البحث عن صور المنتج في الـ meta image)
    img_tag = soup.find('meta', property='og:image')
    images = [img_tag['content']] if img_tag else ["غير متوفر"]
    
    return {
        "product_name": title,
        "product_rating": rating,
        "description": description,
        "images": images
    }
