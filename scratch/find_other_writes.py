import json

transcript_path = r"C:\Users\SarthakMakkar\.gemini\antigravity\brain\115451a5-ce97-4d9d-a4ef-3fe062e18a4c\.system_generated\logs\transcript_full.jsonl"

files_to_track = {
    "configs/config.yaml": [],
    "agents/planner_agent.py": []
}

with open(transcript_path, "r", encoding="utf-8") as f:
    for line in f:
        try:
            data = json.loads(line)
            if "tool_calls" in data:
                for tc in data["tool_calls"]:
                    if tc.get("name") in ["write_to_file", "replace_file_content"]:
                        args = tc.get("args", {})
                        target = args.get("TargetFile") or args.get("Target") or ""
                        for fn in files_to_track:
                            if fn in target.replace("\\", "/"):
                                files_to_track[fn].append((data.get("step_index"), tc.get("name"), args))
        except Exception as e:
            pass

for fn, occurrences in files_to_track.items():
    print(f"\n--- {fn} (total edits: {len(occurrences)}) ---")
    for step_idx, name, args in occurrences:
        print(f"  Step {step_idx}: {name}")
        if name == "write_to_file":
            print("    CodeContent length:", len(args.get("CodeContent", "")))
