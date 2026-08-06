import json

transcript_path = r"C:\Users\SarthakMakkar\.gemini\antigravity\brain\115451a5-ce97-4d9d-a4ef-3fe062e18a4c\.system_generated\logs\transcript_full.jsonl"

def normalize_whitespace(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    import re
    text = re.sub(r'[ \t]+', ' ', text)
    # Remove leading/trailing space per line to handle indentation variations
    lines = [l.strip() for l in text.split("\n")]
    return "\n".join(lines)

with open(transcript_path, "r", encoding="utf-8") as f:
    for line in f:
        try:
            data = json.loads(line)
            if data.get("step_index") == 566:
                tc = data["tool_calls"][0]
                args = tc["args"]
                target_content = args["TargetContent"]
                
                # Let's read the state of agent.py at step 455 (rebuilt content up to step 455)
                # Let's see what is currently in agent.py or rebuilt
                # Let's print first 100 characters of target_content
                print("TargetContent (normalized):")
                print(repr(normalize_whitespace(target_content))[:300])
                break
        except Exception as e:
            pass
