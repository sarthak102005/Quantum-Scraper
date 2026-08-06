with open(r"c:\Users\SarthakMakkar\OneDrive - Short Hills Tech Pvt Ltd\Desktop\desing\autonomous-ai-scraper\autonomous_scraper\agent.py.original", "r", encoding="utf-8") as f:
    content = f.read()
    
print("finalize_crawl in original:", "finalize_crawl" in content)
if "finalize_crawl" in content:
    # Print the function block
    idx = content.find("async def finalize_crawl")
    print(content[idx:idx+400])
