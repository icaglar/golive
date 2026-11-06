#!/usr/bin/env python3
"""golive PostToolUse hook: after every write to the golive state file, refresh
.claude/golive-status.html and hand Claude the status board to show the user.
Fails open: on any error it prints nothing."""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    if payload.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return
    path = str((payload.get("tool_input") or {}).get("file_path", ""))
    if not re.search(r"golive\.ya?ml$", path) or not os.path.exists(path):
        return
    lang = (os.environ.get("CLAUDE_PLUGIN_OPTION_LANGUAGE") or os.environ.get("GOLIVE_LANG") or "en").strip().lower()
    lang = "tr" if lang.startswith("tr") else "en"
    script = os.path.join(HERE, "status.py")
    html_out = os.path.join(os.path.dirname(path), "golive-status.html")
    subprocess.run([sys.executable, script, "--state", path, "--lang", lang, "--format", "html", "--out", html_out],
                   capture_output=True, timeout=8)
    board = subprocess.run([sys.executable, script, "--state", path, "--lang", lang],
                           capture_output=True, text=True, timeout=8).stdout.strip()
    if not board:
        return
    note = ("golive state changed. Show this status board to the user in a code block at the end of your reply, "
            "in their language, unchanged; mention that the visual version is at " + html_out + ".\n\n" + board)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": note}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
