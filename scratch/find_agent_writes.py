import json

transcript_path = r"C:\Users\SarthakMakkar\.gemini\antigravity\brain\115451a5-ce97-4d9d-a4ef-3fe062e18a4c\.system_generated\logs\transcript_full.jsonl"

with open(transcript_path, "r", encoding="utf-8") as f:
    for line in f:
        try:
            data = json.loads(line)
            if "tool_calls" in data:
                for tc in data["tool_calls"]:
                    if tc.get("name") in ["write_to_file", "replace_file_content"]:
                        args = tc.get("args", {})
                        target = args.get("TargetFile") or args.get("Target") or ""
                        if "autonomous_scraper" in target.lower() and "agent.py" in target.lower():
                            # Let's print the step index and the type of write
                            print(f"Step {data.get('step_index')}: {tc.get('name')}")
                            if tc.get("name") == "write_to_file":
                                print("  CodeContent length:", len(args.get("CodeContent", "")))
        except Exception as e:
            pass
