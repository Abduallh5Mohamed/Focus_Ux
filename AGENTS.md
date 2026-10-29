# FOCUS team instructions

Codex is integration lead. Human works across all modules. Read coordination/BOARD.md and relevant docs before editing.

OpenCode is authorized to use subagents. For this milestone use focus-ml (GLM) for ML adapter work and focus-review (DeepSeek) for read-only review. Primary OpenCode owns services/worker and coordinates. No more than two active subagents; no recursive spawning.

Own only product/packages/ml/**, product/services/worker/**, product/tests/ml/** and product/tests/worker/**. DeepSeek external agent owns services/api and tests/api. Product-wide files and API schema changes require Codex review. Delegate disjoint files only; review agent cannot write.

Legacy originals outside this root are read-only and need not be accessed: use legacy_snapshot. Never modify snapshots, download weights or run GPU benchmarks for this milestone. No model training, deployment, push or paid services.

No fake inference success. A fake adapter may exist only in tests. Document unavailable real GPU execution clearly. Tests must exercise selection identity, fps alignment and worker state transitions where implemented.

Write factual handoff to coordination/OPENCODE_HANDOFF.md with changed files, commands, observed results and blockers. Do not claim to message another agent unless delivery actually occurred. Codex owns BOARD.md.


## Round 2 authorization update (supersedes earlier milestone restrictions)
Read coordination/OPENCODE_ROUND2_PROMPT.md and ROUND2_INTEGRATION_DECISIONS.md. Real local GPU inference, read-only legacy code/cache/GT access and project-local runtime outputs are now authorized. Preserve original assets/environment. No weight downloads, training, public deploy or push.
OpenCode primary may delegate to focus-ml and focus-api simultaneously (max two active), followed by focus-review. Managed focus-api owns services/api and tests/api, including its local requirements. External DeepSeek is review-only pending reconciliation. Primary owns services/worker, tests/worker, product/tools/run_local.ps1 and integration status/handoff. ML owns packages/ml, tests/ml and product/tools/verify_gpu.py. WorkBuddy retains frontend. Do not create overlapping writers.
Python stdlib, current runtimes and existing weights first. Missing deps may be installed only into a dedicated product-local environment without changing global/legacy packages. Real inference validation must remain clearly separated from fake-backed tests.
