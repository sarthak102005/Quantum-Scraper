import json

transcript_path = r"C:\Users\SarthakMakkar\.gemini\antigravity\brain\115451a5-ce97-4d9d-a4ef-3fe062e18a4c\.system_generated\logs\transcript_full.jsonl"

agent_views = []
planner_views = []

with open(transcript_path, "r", encoding="utf-8") as f:
    for line in f:
        try:
            data = json.loads(line)
            step_idx = data.get("step_index")
            if step_idx >= 1899:
                break
            
            # Look for SYSTEM/tool output from view_file calls
            if data.get("source") == "SYSTEM" and "content" in data:
                content_str = data.get("content", "")
                if "File Path: " in content_str:
                    if "autonomous_scraper/agent.py" in content_str or "autonomous_scraper\\agent.py" in content_str:
                        # Extract the actual code text shown
                        lines = content_str.split("\n")
                        # The code lines start after "Showing lines..."
                        code_lines = []
                        in_code = False
                        for l in lines:
                            if l.startswith("Showing lines "):
                                in_code = True
                                continue
                            if in_code:
                                # Strip line prefix like "123: "
                                parts = l.split(":", 1)
                                if len(parts) == 2 and parts[0].strip().isdigit():
                                    code_lines.append(parts[1][1:]) # strip the space after colon
                        if code_lines:
                            agent_views.append((step_idx, "\n".join(code_lines)))
                    
                    if "agents/planner_agent.py" in content_str:
                        lines = content_str.split("\n")
                        code_lines = []
                        in_code = False
                        for l in lines:
                            if l.startswith("Showing lines "):
                                in_code = True
                                continue
                            if in_code:
                                parts = l.split(":", 1)
                                if len(parts) == 2 and parts[0].strip().isdigit():
                                    code_lines.append(parts[1][1:])
                        if code_lines:
                            planner_views.append((step_idx, "\n".join(code_lines)))
        except Exception as e:
            pass

print(f"Found agent views before step 1899: {[v[0] for v in agent_views]}")
print(f"Found planner views before step 1899: {[v[0] for v in planner_views]}")

# If we found views, we can save the most recent one
if agent_views:
    last_step, content = agent_views[-1]
    print(f"Last agent.py view was at step {last_step}")
    with open(r"c:\Users\SarthakMakkar\OneDrive - Short Hills Tech Pvt Ltd\Desktop\desing\autonomous-ai-scraper\autonomous_scraper\agent.py.viewed", "w", encoding="utf-8") as f:
        f.write(content)

if planner_views:
    last_step, content = planner_views[-1]
    print(f"Last planner_agent.py view was at step {last_step}")
    with open(r"c:\Users\SarthakMakkar\OneDrive - Short Hills Tech Pvt Ltd\Desktop\desing\autonomous-ai-scraper\agents\planner_agent.py.viewed", "w", encoding="utf-8") as f:
        f.write(content)
