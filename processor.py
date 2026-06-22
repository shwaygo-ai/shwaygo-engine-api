from bs4 import BeautifulSoup

def process_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # محاولة إيجاد اسم المنتج
    title_tag = soup.find('h1', {'data-spm-anchor-id': None}) or soup.find('span', {'class': 'product-title-text'})
    
    # استخراج النص إذا وجد التاج، وإلا وضع رسالة خطأ
    title = title_tag.text.strip() if title_tag else "لم يتم العثور على اسم المنتج"
    
    return {
        "product_name": title
    }
