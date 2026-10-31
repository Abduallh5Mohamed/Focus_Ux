# Main integration verification (2026-10-31)

Merged origin/main 67f76fb98980fa8fe598e140cab658b71fa7c08f with branch عبدو 349957f788a7863bdffb7be70fb3baadc1bc9501.

Conflicts resolved in voice/engine.py, API inference.py and test_voice_flow.py. Preserved main's strict/continuity and WeSep routing, reference audio and routing summaries. Explicit FOCUS_VOICE_EXTRACTOR selects the separation/music/ducked adapter; unset keeps main's routed default. Identity extraction retains embedder through final verification and releases it afterward. Both API routing notices and local extractor warnings survive. Removed duplicated placeholder test definition and changed ducking-specific tests to opt into ducking explicitly. Replaced a machine-specific setup documentation path with a portable relative example.

Validation on merged tree:
- voice + ML: 205 passed, 1 skipped.
- overlap: 99 passed (fake-backed tests, not new real model validation).
- inference + worker: 124 passed.
- API: 250 passed, 1 skipped.
- Web: 115 passed across 13 files; production build passed.
- Total Python: 678 passed, 2 skipped.
- Diff whitespace check passed with cr-at-eol for upstream Windows batch files.

An initial all-suites-in-one-process attempt had a fakes module import collision; suites were rerun in independent processes. Two initial branch tests assumed ducking was default; they now explicitly request ducking, retaining main's strict default. Portable setup test initially found a fixed drive in a docstring; fixed and rerun. No new real GPU benchmark was claimed during this merge. Local logs and .workbuddy-ai remain untracked.

## Superseding user direction
The user explicitly designated branch عبدو (349957f788a7863bdffb7be70fb3baadc1bc9501) as the authoritative working product and rejected integration changes to that code. After merge 8341d0e had already reached main, the entire product/ subtree was restored exactly to that branch snapshot in a forward corrective commit. The merge-validation results above describe the superseded merge, not the restored code. Upstream-only product additions, including WeSep routing, are absent from the restored product; they remain in Git history. The restored product is the previously tested baseline (547 Python tests passed, 4 skipped, plus 3 later session-recovery tests and TypeScript check). No new execution result is claimed for this correction. Verified git diff against the baseline has no product differences. Documentation outside product may describe upstream features absent from this restored snapshot; use the product code and CODEX_GPU_QUALITY_RESULT_2026-10-31.md as the baseline reference.
