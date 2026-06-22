import json
from bs4 import BeautifulSoup
import re

def process_html(html_content):
    # البحث عن البيانات المخفية التي تحتوي على اسم المنتج
    match = re.search(r'window\.runParams\s*=\s*({.*?});', html_content)
    
    if match:
        try:
            data = json.loads(match.group(1))
            # استخراج الاسم من البيانات الهيكلية
            title = data.get('data', {}).get('pageModule', {}).get('title', "لم يتم العثور على اسم المنتج")
            return {"product_name": title}
        except:
            return {"product_name": "خطأ في معالجة البيانات"}
    
    return {"product_name": "لم يتم العثور على اسم المنتج في البيانات الهيكلية"}
