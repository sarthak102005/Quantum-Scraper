import json

transcript_path = r"C:\Users\SarthakMakkar\.gemini\antigravity\brain\115451a5-ce97-4d9d-a4ef-3fe062e18a4c\.system_generated\logs\transcript_full.jsonl"

found_content = None
with open(transcript_path, "r", encoding="utf-8") as f:
    for line in f:
        try:
            data = json.loads(line)
            if data.get("step_index") == 455:
                for tc in data["tool_calls"]:
                    if tc.get("name") == "write_to_file":
                        found_content = tc.get("args", {}).get("CodeContent")
                        break
        except Exception as e:
            pass

if found_content:
    original_file_path = r"c:\Users\SarthakMakkar\OneDrive - Short Hills Tech Pvt Ltd\Desktop\desing\autonomous-ai-scraper\autonomous_scraper\agent.py.original"
    with open(original_file_path, "w", encoding="utf-8") as f:
        f.write(found_content)
    print("Successfully extracted original agent.py content from Step 455!")
else:
    print("Could not find agent.py content at Step 455.")
