# Lessons inbox — NOT rules; waiting for Claude to verify

Render-only agents (agy, codex) append new lessons here instead of editing the other references.
Once `videotool agent lesson` exists, use it (it appends here and messages the user). Until then
append by hand AND tell the user in the session. When the user asks, Claude verifies each entry
against code/logs and moves it into the right reference, then deletes it from this file.

Entry format:

```
## YYYY-MM-DD <agent> <episode slug>
- What happened:
- Evidence (log line, file, command output):
- Suggested rule:
```

## 2026-10-09 01:33 UTC · claude · ke-tru-ta-chap01
- What happened: the first 'modal run' sat for ~30 min after 'Built image' with no 'Created objects' line; the client had sent ~786 MB of the 1.3 GB job folder, then sent nothing for 15 min (CPU idle, threads in futex wait, no container). Stopped with Ctrl-C (app 'stopped', no GPU cost) and relaunched: the retry printed 'Uploaded 0 new files' / 'Uploaded 1 new files and 2743703 bytes' and reached 'render start' in under a minute, so Modal had kept the blobs from the first try. Evidence: ~/.cache/videotool/ke-tru-ta-chap01-modal-try1.log (ends at 'Built image im-ZsFr…'), ke-tru-ta-chap01-modal.log (MODAL_LOGLEVEL=DEBUG upload lines 15:40:34-35). The upload, not the image build (7 s, cached), is the slow step: ~1.3 GB per episode (Parallax/ 647 MB + WAV 391 MB) at ~0.8 MB/s average to Modal, while rclone to Drive ran at ~15 MiB/s the same day. Suggested rule (modal-runbook Gotchas): no 'Created objects' and no upload progress for 10 min -> Ctrl-C and rerun, blobs are kept; run with MODAL_LOGLEVEL=DEBUG to see the upload lines; the modal CLI is on PATH (~/.local/bin/modal), not in .venv.

## 2026-10-09 01:33 UTC · claude · ke-tru-ta-chap10
- What happened: the Chinese source NGUỒN TRUYỆN/Truyện chưa dịch - txt/6. Kẻ trừ tà/驱魔人.txt repeats chapters and the split + translation carry the repeats. Evidence (n-gram overlap, unrelated chapters ~0.06; plans/reports/ktt-youtube-titles-261008-2209-tap-01-10.md 'Source defect'): block A, chapters 120-152 repeat 87-119 in order (Vietnamese 0.34-0.54, Chinese 0.96-1.00); headings of chapters 103-119 do not match their text; block B pairs 210/177, 214/181, 216/183, 226-232/193-199, 234-235/201-202, 238-239/205-206 (0.34-0.48). No audio exists yet for an affected range (OMNI Tập 1-7, VIENEU Tập 1-3). Fixing the source is the user's call. Suggested rule: a lint/inspect check that flags two chapters of one series with high text overlap (> ~0.3 n-gram) or a heading that does not match its text, before titles, audio or a render are made for the range.
