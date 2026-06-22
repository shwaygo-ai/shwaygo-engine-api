from bs4 import BeautifulSoup

def process_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. الاسم
    title_tag = soup.find('meta', property='og:title')
    title = title_tag['content'] if title_tag else "لا يوجد اسم"
    
    # 2. التقييم (نبحث عن الـ span الذي يحتوي على التقييم)
    rating_tag = soup.find('span', {'class': 'overview-rating-average'})
    rating = rating_tag.text.strip() if rating_tag else "لا يوجد تقييم"
    
    # 3. الوصف (نبحث عن الـ div الخاص بوصف المنتج)
    desc_tag = soup.find('div', {'id': 'product-description'})
    description = desc_tag.text.strip() if desc_tag else "لا يوجد وصف"
    
    # 4. الصور (نجمع روابط الصور)
    images = [img['src'] for img in soup.find_all('img', {'class': 'magnifier-image'})]
    
    return {
        "product_name": title,
        "product_rating": rating,
        "description": description,
        "images": images if images else ["لا توجد صور"]
    }
