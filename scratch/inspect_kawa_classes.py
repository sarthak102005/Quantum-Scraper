import asyncio
import aiohttp
from bs4 import BeautifulSoup

async def main():
    url = "https://www.kawasaki.com/en-us/shop/holiday-gift-guides/gifts-under-100"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            html = await resp.text()
            soup = BeautifulSoup(html, 'html.parser')
            
            # Find class names
            classes = set()
            for el in soup.find_all(class_=True):
                classes.update(el['class'])
            
            print("Unique classes:")
            for c in sorted(classes):
                if any(x in c.lower() for x in ['product', 'grid', 'card', 'tile', 'item', 'list']):
                    print("Class:", c)

if __name__ == "__main__":
    asyncio.run(main())
