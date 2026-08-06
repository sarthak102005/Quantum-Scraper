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
            
            # Print page title and potential model names
            print("Title:", soup.title.get_text() if soup.title else "No Title")
            
            # Find any tables, specs, or JSON-LD
            scripts = soup.find_all("script", type="application/ld+json")
            print("JSON-LD blocks found:", len(scripts))
            for idx, s in enumerate(scripts):
                print(f"Block {idx} snippet:", s.string[:200] if s.string else "None")
                
            # Search for spec sheets or specs content
            spec_divs = soup.find_all(class_=lambda c: c and any(x in c.lower() for x in ['spec', 'model', 'feature']))
            print("Spec-related divs:", len(spec_divs))
            
            # Look for model-specific anchor links on this page
            model_anchors = []
            for a in soup.find_all("a", href=True):
                href = a['href']
                if "medium-air-compressors" in href and href != "/in/en/equipment/air-compressors/medium-air-compressors":
                    model_anchors.append((href, a.get_text(strip=True)))
            print("Medium Air Compressor related anchors:")
            for m in set(model_anchors):
                print(" -> Href:", m[0], "Text:", m[1])

if __name__ == "__main__":
    asyncio.run(main())
