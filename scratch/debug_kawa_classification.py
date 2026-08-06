import asyncio
import logging
import sys
from urllib.parse import urlsplit

# Add workspace to path
sys.path.append("c:\\Users\\SarthakMakkar\\OneDrive - Short Hills Tech Pvt Ltd\\Desktop\\desing\\autonomous-ai-scraper")

from shared.models.website_profile import WebsiteProfile
from mcps.classification.classification_mcp import ClassificationMCP
from mcps.classification.heuristics import collect_evidence, DEFAULT_WEIGHTS
from mcps.execution.execution_mcp import ExecutionMCP
from shared.utils.config import get_config

async def test_classification():
    url = "https://www.kawasaki.com/en-us/shop/holiday-gift-guides/gifts-under-100"
    config = get_config()
    profile = WebsiteProfile(domain="kawasaki.com", seed_url="https://www.kawasaki.com/en-us/")
    
    execution = ExecutionMCP(config)
    fetch_res = await execution.smart_fetch(url, profile)
    
    # Collect evidence
    signals = collect_evidence(url, fetch_res.html, profile)
    print("Signals fired:")
    for sig, fired in signals.items():
        if fired:
            print(f" - {sig}")
            
    # Calculate scores for each PageType
    for page_type, weights in DEFAULT_WEIGHTS.items():
        score = 0.0
        applied = []
        for signal_name, weight in weights.items():
            if signals.get(signal_name):
                score += weight
                applied.append(f"{signal_name}({weight})")
        print(f"PageType: {page_type}, Score: {score}, Applied: {applied}")
        
    await execution.close()

if __name__ == "__main__":
    asyncio.run(test_classification())
