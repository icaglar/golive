---
name: status
description: Shows where the go-live stands as a status board - progress bar, the steps grouped by phase (domain, infrastructure, release, mail, operations, compliance) with done / in progress / pending / blocked / skipped, the next step, what is waiting for the user and what is still missing - in the chat and as a visual HTML page. Use when the user asks "ne durumdayız", "neredeyiz", "ilerleme", "kalan ne", "status", "progress", or after any golive step.
---

# Go-live status board

Talk to the user in the language they use.

1. Run, with `--lang tr` for Turkish and `--lang en` otherwise:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" --state .claude/golive.yaml --lang tr
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" --state .claude/golive.yaml --lang tr --format html --out .claude/golive-status.html
   ```
2. Show the text board **unchanged in a code block**, then at most two lines: what is next, and anything the user must do (the ⛔ items). Steps that run per environment show progress inline (`Deploy (staging ✅, prod ⏳)`) and count as done only when every environment is done; the header carries the running monthly total (`≈ 42.50 EUR/month`) from `costs:` in the state file, omitted when nothing is billed yet.
3. The visual version is `.claude/golive-status.html`. Where the session can show files (Cowork, claude.ai), deliver it so it renders, or publish it as a page if the user wants to share it; in a terminal, give its path.

The PostToolUse hook refreshes the HTML and hands you the board every time `.claude/golive.yaml` is written with Write or Edit; when you changed the state another way (a script, `sed`), run step 1 yourself. Every golive step ends with this board.
