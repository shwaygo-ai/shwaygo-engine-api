from bs4 import BeautifulSoup

def process_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    # البحث عن الميتا تاج التي تحتوي على العنوان (طريقة مضمونة أكثر)
    title_tag = soup.find('meta', property='og:title')
    title = title_tag['content'] if title_tag else "لم يتم العثور على اسم المنتج"
    
    return {
        "product_name": title
    }
