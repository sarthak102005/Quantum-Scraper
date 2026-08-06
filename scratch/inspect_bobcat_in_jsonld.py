import asyncio
import aiohttp
from bs4 import BeautifulSoup
import json

async def main():
    url = "https://www.bobcat.com/in/en/equipment/air-compressors/medium-air-compressors/475-575-cfm"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            html = await resp.text()
            soup = BeautifulSoup(html, 'html.parser')
            
            # Print full JSON-LD
            scripts = soup.find_all("script", type="application/ld+json")
            for idx, s in enumerate(scripts):
                try:
                    js = json.loads(s.string)
                    print(f"JSON-LD Block {idx}:")
                    print(json.dumps(js, indent=2)[:1000])
                except Exception as e:
                    print("Error parsing JSON:", e)

            # Let's inspect some headers or model text on the page
            print("\nH1 headers:")
            for h in soup.find_all("h1"):
                print("H1:", h.get_text(strip=True))

            print("\nH2 headers:")
            for h in soup.find_all("h2")[:10]:
                print("H2:", h.get_text(strip=True))

if __name__ == "__main__":
    asyncio.run(main())
