import json
import os

transcript_path = r"C:\Users\SarthakMakkar\.gemini\antigravity\brain\115451a5-ce97-4d9d-a4ef-3fe062e18a4c\.system_generated\logs\transcript_full.jsonl"

def normalize_lines(text):
    if not text:
        return ""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines)

def apply_clean_patch(source_content, target_chunk, replacement_chunk):
    src_norm = normalize_lines(source_content)
    tar_norm = normalize_lines(target_chunk)
    rep_norm = normalize_lines(replacement_chunk)
    
    if tar_norm in src_norm:
        return src_norm.replace(tar_norm, rep_norm)
    return None

def rebuild_files_with_success_only(target_step_cutoff):
    # Pass 1: Parse all steps sequentially and identify tool calls and their success status
    steps_list = []
    
    # We will read all lines in order
    raw_steps = []
    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                raw_steps.append(json.loads(line))
            except Exception as e:
                pass
                
    for i, data in enumerate(raw_steps):
        step_idx = data.get("step_index")
        if step_idx > target_step_cutoff:
            break
            
        source = data.get("source")
        step_type = data.get("type")
        
        if source == "MODEL" and step_type == "PLANNER_RESPONSE":
            tool_calls = data.get("tool_calls", [])
            if not tool_calls:
                continue
                
            # Look at the next step to see if it is an error
            is_success = True
            if i + 1 < len(raw_steps):
                next_step = raw_steps[i + 1]
                next_type = next_step.get("type")
                next_content = next_step.get("content", "")
                if next_type == "ERROR_MESSAGE" or "invalid tool call" in next_content.lower() or "encountered error" in next_content.lower():
                    is_success = False
            
            steps_list.append({
                "step_index": step_idx,
                "tool_calls": tool_calls,
                "success": is_success
            })

    # Pass 2: Reconstruct files
    files = {}
    
    for step in steps_list:
        step_idx = step["step_index"]
        success = step["success"]
        
        for tc in step["tool_calls"]:
            name = tc.get("name")
            args = tc.get("args", {})
            target = args.get("TargetFile") or args.get("Target") or ""
            target_norm = target.replace("\\", "/").lower()
            
            if not target_norm:
                continue
                
            # We track all modified files
            if target_norm not in files:
                files[target_norm] = None
                
            if name == "write_to_file":
                if success:
                    files[target_norm] = args.get("CodeContent")
                    print(f"[{target_norm}] Re-initialized at step {step_idx}")
                else:
                    print(f"[{target_norm}] Ignored failed write_to_file at step {step_idx}")
                    
            elif name == "replace_file_content":
                target_content = args.get("TargetContent")
                replacement_content = args.get("ReplacementContent")
                current_content = files[target_norm]
                
                if current_content is not None and target_content and replacement_content:
                    if success:
                        patched = apply_clean_patch(current_content, target_content, replacement_content)
                        if patched is not None:
                            files[target_norm] = patched
                            print(f"[{target_norm}] Applied patch at step {step_idx}")
                        else:
                            print(f"[{target_norm}] WARNING: Patch mismatched at step {step_idx}!")
                    else:
                        print(f"[{target_norm}] Ignored failed/errored patch at step {step_idx}")
                        
    return files

# Rebuild files at step 1900 (the clean state before we started editing fallback rules)
rebuilt_files = rebuild_files_with_success_only(1900)

# Save the rebuilt files to disk
for path_norm, content in rebuilt_files.items():
    if content is None:
        continue
    # Ensure parent dir exists
    os.makedirs(os.path.dirname(path_norm), exist_ok=True)
    with open(path_norm, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Saved rebuilt file to {path_norm}")
