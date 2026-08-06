import sys
import os

project_root = r"c:\Users\SarthakMakkar\OneDrive - Short Hills Tech Pvt Ltd\Desktop\desing\autonomous-ai-scraper"

for root, dirs, files in os.walk(project_root):
    for f in files:
        if f.endswith(".py"):
            path = os.path.join(root, f)
            with open(path, "r", encoding="utf-8", errors="ignore") as file:
                content = file.read()
                if "planner_agent" in content:
                    print(f"File: {path}")
                    # Find lines with planner_agent
                    for line in content.split("\n"):
                        if "planner_agent" in line:
                            print("  ", line)
