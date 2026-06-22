from bs4 import BeautifulSoup

def process_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # استخراج اسم المنتج
    title_tag = soup.find('h1')
    title = title_tag.text.strip() if title_tag else "لا يوجد عنوان"
    
    return {
        "product_name": title
    }
