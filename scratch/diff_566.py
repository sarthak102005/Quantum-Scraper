import json
import difflib

transcript_path = r"C:\Users\SarthakMakkar\.gemini\antigravity\brain\115451a5-ce97-4d9d-a4ef-3fe062e18a4c\.system_generated\logs\transcript_full.jsonl"

def normalize_whitespace(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text

# Read step 455 original content
with open(r"c:\Users\SarthakMakkar\OneDrive - Short Hills Tech Pvt Ltd\Desktop\desing\autonomous-ai-scraper\autonomous_scraper\agent.py.original", "r", encoding="utf-8") as f:
    orig_content = f.read()

# Get step 566 target content
target_content = None
with open(transcript_path, "r", encoding="utf-8") as f:
    for line in f:
        try:
            data = json.loads(line)
            if data.get("step_index") == 566:
                target_content = data["tool_calls"][0]["args"]["TargetContent"]
                break
        except Exception as e:
            pass

if orig_content and target_content:
    orig_norm = normalize_whitespace(orig_content)
    target_norm = normalize_whitespace(target_content)
    
    print("Length of target_norm:", len(target_norm))
    # Search for a subsegment of target_norm in orig_norm
    sub_target = target_norm[:50]
    idx = orig_norm.find(sub_target)
    print("Found subtarget in orig_norm:", idx != -1)
    if idx != -1:
        # Print the segment in orig_norm of the same length
        matched_segment = orig_norm[idx:idx+len(target_norm)]
        print("Length of matched segment in orig_norm:", len(matched_segment))
        # Print the exact diff
        diff = list(difflib.unified_diff(
            target_norm.splitlines(),
            matched_segment.splitlines(),
            fromfile='target',
            tofile='matched'
        ))
        print("Diff lines count:", len(diff))
        for line in diff[:30]:
            print(line)
