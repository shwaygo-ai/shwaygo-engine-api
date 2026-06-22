import os
from zenrows import ZenRowsClient
from fastapi import FastAPI, Body

app = FastAPI()

client = ZenRowsClient(os.getenv("ZENROWS_API_KEY"))

@app.post("/scrape")
async def scrape_product(data: dict = Body(...)):
    url = data.get("url")
    params = {
        "js_render": "true",
        "antibot": "true",
        "premium_proxy": "true"
    }
    response = client.get(url, params)
    return {"content": response.text}
