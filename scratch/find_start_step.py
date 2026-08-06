import json

transcript_path = r"C:\Users\SarthakMakkar\.gemini\antigravity\brain\115451a5-ce97-4d9d-a4ef-3fe062e18a4c\.system_generated\logs\transcript.jsonl"

first_steps = []
with open(transcript_path, "r", encoding="utf-8") as f:
    for i, line in enumerate(f):
        if i < 15:
            try:
                data = json.loads(line)
                first_steps.append((data.get("step_index"), data.get("type")))
            except Exception as e:
                pass
print(first_steps)
