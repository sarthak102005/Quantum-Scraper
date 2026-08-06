import asyncio
import aiohttp
from bs4 import BeautifulSoup
import json

async def main():
    url = "https://www.kawasaki.com/en-us/shop/holiday-gift-guides/gifts-under-100"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            html = await resp.text()
            soup = BeautifulSoup(html, 'html.parser')
            print("Status:", resp.status)
            print("Title:", soup.title.get_text() if soup.title else "No Title")
            
            # Print JSON-LD
            scripts = soup.find_all("script", type="application/ld+json")
            print("JSON-LD count:", len(scripts))
            for i, s in enumerate(scripts):
                try:
                    js = json.loads(s.string)
                    print(f"Block {i} type:", type(js))
                    if isinstance(js, list):
                        for item in js:
                            print("  Type in list:", item.get("@type"))
                    else:
                        print("  Type:", js.get("@type"))
                except Exception as e:
                    print("Error parsing:", e)

            # Let's inspect headings
            print("\nH1 headers:")
            for h in soup.find_all("h1"):
                print("H1:", h.get_text(strip=True))

            # Is there any product grid elements?
            print("\nCompare products elements present?", "compare" in html.lower())

if __name__ == "__main__":
    asyncio.run(main())
