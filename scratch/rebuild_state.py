import json
import re

transcript_path = r"C:\Users\SarthakMakkar\.gemini\antigravity\brain\115451a5-ce97-4d9d-a4ef-3fe062e18a4c\.system_generated\logs\transcript_full.jsonl"

def normalize_lines(text):
    # Split, strip trailing space from every line, and join with standard line endings
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines)

def apply_clean_patch(source_content, target_chunk, replacement_chunk):
    # Normalize line endings and strip trailing spaces
    src_norm = normalize_lines(source_content)
    tar_norm = normalize_lines(target_chunk)
    rep_norm = normalize_lines(replacement_chunk)
    
    if tar_norm in src_norm:
        patched = src_norm.replace(tar_norm, rep_norm)
        # Restore CRLF if needed (or just save standard Unix endings which Python handles natively on write)
        return patched
    return None

def rebuild_file_at_step(target_file_pattern, target_step_cutoff):
    current_content = None
    
    # Read the transcript sequentially
    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                data = json.loads(line)
                step_idx = data.get("step_index")
                if step_idx > target_step_cutoff:
                    break
                
                if "tool_calls" in data:
                    for tc in data["tool_calls"]:
                        name = tc.get("name")
                        args = tc.get("args", {})
                        target = args.get("TargetFile") or args.get("Target") or ""
                        
                        if target_file_pattern in target.replace("\\", "/"):
                            if name == "write_to_file":
                                current_content = args.get("CodeContent")
                                print(f"[{target_file_pattern}] Re-initialized at step {step_idx}")
                            elif name == "replace_file_content":
                                target_content = args.get("TargetContent")
                                replacement_content = args.get("ReplacementContent")
                                if current_content is not None and target_content and replacement_content:
                                    patched = apply_clean_patch(current_content, target_content, replacement_content)
                                    if patched is not None:
                                        current_content = patched
                                        print(f"[{target_file_pattern}] Applied patch at step {step_idx}")
                                    else:
                                        print(f"[{target_file_pattern}] WARNING: Patch mismatch at step {step_idx}!")
            except Exception as e:
                pass
    return current_content

# Rebuild files at step 1800 (before we did any fallback code modifications)
agent_py_content = rebuild_file_at_step("autonomous_scraper/agent.py", 1800)
planner_py_content = rebuild_file_at_step("agents/planner_agent.py", 1800)
config_yaml_content = rebuild_file_at_step("configs/config.yaml", 1800)

if agent_py_content:
    with open(r"c:\Users\SarthakMakkar\OneDrive - Short Hills Tech Pvt Ltd\Desktop\desing\autonomous-ai-scraper\autonomous_scraper\agent.py", "w", encoding="utf-8") as f:
        f.write(agent_py_content)
    print("Rebuilt and restored autonomous_scraper/agent.py")

if planner_py_content:
    with open(r"c:\Users\SarthakMakkar\OneDrive - Short Hills Tech Pvt Ltd\Desktop\desing\autonomous-ai-scraper\agents\planner_agent.py", "w", encoding="utf-8") as f:
        f.write(planner_py_content)
    print("Rebuilt and restored agents/planner_agent.py")

if config_yaml_content:
    with open(r"c:\Users\SarthakMakkar\OneDrive - Short Hills Tech Pvt Ltd\Desktop\desing\autonomous-ai-scraper\configs\config.yaml", "w", encoding="utf-8") as f:
        f.write(config_yaml_content)
    print("Rebuilt and restored configs/config.yaml")
