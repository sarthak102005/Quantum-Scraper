import json
import sys

transcript_path = r"C:\Users\SarthakMakkar\.gemini\antigravity\brain\115451a5-ce97-4d9d-a4ef-3fe062e18a4c\.system_generated\logs\transcript.jsonl"

steps = []
with open(transcript_path, "r", encoding="utf-8") as f:
    for line in f:
        try:
            data = json.loads(line)
            if "tool_calls" in data:
                for tc in data["tool_calls"]:
                    if tc.get("name") == "replace_file_content":
                        args = tc.get("args", {})
                        target = args.get("TargetFile") or args.get("Target") or ""
                        if "autonomous_scraper" in target.lower() and "agent.py" in target.lower():
                            steps.append((data.get("step_index"), args))
        except Exception as e:
            pass

# Let's read the current contents of autonomous_scraper/agent.py
current_file_path = r"c:\Users\SarthakMakkar\OneDrive - Short Hills Tech Pvt Ltd\Desktop\desing\autonomous-ai-scraper\autonomous_scraper\agent.py"
with open(current_file_path, "r", encoding="utf-8") as f:
    current_content = f.read()

# Let's perform reverse modifications in reverse chronological order
print(f"Applying reverse modifications. Total steps: {len(steps)}")
reverted_content = current_content
for step_index, args in reversed(steps):
    target_content = args.get("TargetContent")
    replacement_content = args.get("ReplacementContent")
    
    # If they are strings representing json/escaped text, normalize them
    # TargetContent/ReplacementContent in the JSON is already a string, but the parser serialized it
    # Let's make sure they are strings
    if isinstance(target_content, str) and isinstance(replacement_content, str):
        # Revert: replace replacement_content back to target_content
        if replacement_content in reverted_content:
            reverted_content = reverted_content.replace(replacement_content, target_content)
            print(f"Successfully reverted step {step_index}")
        else:
            # Let's try stripping whitespaces or CRLF variations
            rep_norm = replacement_content.replace("\r\n", "\n")
            tar_norm = target_content.replace("\r\n", "\n")
            rev_norm = reverted_content.replace("\r\n", "\n")
            if rep_norm in rev_norm:
                rev_norm = rev_norm.replace(rep_norm, tar_norm)
                reverted_content = rev_norm
                print(f"Successfully reverted step {step_index} with CRLF normalization")
            else:
                print(f"Could not find exact replacement content for step {step_index} in file!")
                # Print length comparison
                print(f"  Replacement len: {len(replacement_content)}, Target len: {len(target_content)}")

# Let's save the reverted content
with open(r"c:\Users\SarthakMakkar\OneDrive - Short Hills Tech Pvt Ltd\Desktop\desing\autonomous-ai-scraper\autonomous_scraper\agent.py.reverted", "w", encoding="utf-8") as f:
    f.write(reverted_content)
print("Saved reverted content.")
