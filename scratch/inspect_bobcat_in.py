import asyncio
import aiohttp
from bs4 import BeautifulSoup

async def main():
    url = "https://www.bobcat.com/in/en/equipment/air-compressors/medium-air-compressors/475-575-cfm"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            html = await resp.text()
            soup = BeautifulSoup(html, 'html.parser')
            print("Status:", resp.status)
            print("Title:", soup.title.get_text() if soup.title else "No Title")
            print("DOM size:", len(html))
            
            # Print some links
            anchors = soup.find_all("a", href=True)
            print("Total anchors:", len(anchors))
            for a in anchors[:15]:
                print("Href:", a['href'], "Text:", a.get_text(strip=True))

if __name__ == "__main__":
    asyncio.run(main())
