import json

transcript_path = r"C:\Users\SarthakMakkar\.gemini\antigravity\brain\115451a5-ce97-4d9d-a4ef-3fe062e18a4c\.system_generated\logs\transcript_full.jsonl"

with open(transcript_path, "r", encoding="utf-8") as f:
    for line in f:
        try:
            data = json.loads(line)
            step_idx = data.get("step_index")
            if 450 <= step_idx <= 460:
                print(f"Step {step_idx}: Source: {data.get('source')}, Type: {data.get('type')}")
                if "tool_calls" in data:
                    for tc in data["tool_calls"]:
                        print(f"  Tool Call: {tc.get('name')}")
                        args = tc.get("args", {})
                        print(f"    TargetFile: {args.get('TargetFile') or args.get('Target')}")
                if "content" in data:
                    print(f"  Content snippet: {repr(data.get('content')[:150])}")
        except Exception as e:
            pass
