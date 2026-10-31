# Quiet-speaker extraction: baseline findings and status

Written from the code at the start of the repair (branch `task-92-quiet-speaker-repair`), not from earlier summaries.

## Verified root causes (each tied to code)
1. Only UNCERTAIN regions with reason `overlap` ever reached the extractor (`overlap/hybrid.py`, `overlap_spans`).
   Weak-match, too-short and OTHER-labelled regions were never attempted, so a quiet target the diarizer or
   matcher missed was muted without any recovery try.
2. Fragmented short turns of the target stayed uncertain (`voice/match.py`).
3. The post-extraction voiceprint check used the full-band threshold on 8 kHz model output (`HybridExtractor._check_piece`).
4. A missing checkpoint was noticed only if a window ran; non-Blocked exceptions crashed the job (`voice/routing.py`).
5. Continuity mode replayed confident-OTHER speech, contradicting its docstring.
6. Strict mode gave no possible-target-loss notice; skipped extraction had no warning.
7. The worker did not check code version or request contract; a vanished worker errored only after the full timeout (`remote_inference.py`).

## Unverified suspicions (not measured)
* How much recovery helps with real WeSep weights, and the false-accept rate when OTHER regions are recovered.
* The 42% digital-silence figure came from an earlier real output analysis; it was not reproduced here.

## What is done, by evidence level
| Level | Status |
|---|---|
| Implemented | Recovery windows, short-turn joining, band-matched identity, never-louder-than-mixture guard, strict/continuity labelling, route labels, result-screen notes, code-version handshake, isolate contract, disconnect errors, missing-enrollment error |
| Unit-tested (mocks: tone speakers, FakeEmbedder, ToneExtractor) | `product/tests/overlap/test_quiet_speaker.py`, `product/tests/inference/test_worker_contract.py`, updated overlap/worker/api/web tests |
| Real-model-tested | NOT DONE |
| GPU-tested | NOT DONE (no GPU in Replit; no VRAM, speed or SI-SDRi figures exist) |
| Website-tested | NOT DONE with a real worker; only the API test client |

The extractor stays default-off and research-only (the WeSep checkpoint has no explicit licence).

## Commands for the Windows laptop (unchanged, in this order)
See `docs/WESEP_WEBSITE_TRIAL.md` steps 2 to 5 (`git pull --ff-only`, `Check-Connection.cmd`, `Overlap-Validate.cmd ...`,
`set FOCUS_OVERLAP_EXTRACTOR=wesep_bsrnn` then `Start-Worker-Checkout.cmd`) and `docs/OVERLAP_PRODUCTION.md`
(preflight and minimal inference). The quiet-target acceptance case is: target quieter than interferer,
retention high, leakage low, measured by `product/tools/overlap_acceptance.py`.
