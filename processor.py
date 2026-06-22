from bs4 import BeautifulSoup

def process_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # استخراج اسم المنتج
    # البحث عن اسم المنتج في الـ h1 أو الـ span المخصص
    title_tag = soup.find('h1', {'data-spm-anchor-id': None}) or soup.find('span', {'class': 'product-title-text'})
    title = title_tag.text.strip() if title_tag else "لم يتم العثور على اسم المنتج"
    title = title_tag.text.strip() if title_tag else "لا يوجد عنوان"
    
    return {
        "product_name": title
    }
