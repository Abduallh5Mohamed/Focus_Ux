# Dev 1 — المحرك والتتبع والسرعة

## ملكيتك
`packages/ml/` و`services/worker/`. تنسق بروتوكول Job مع Dev 2، ولا تعيد كتابة UI أو API.

## اليوم الأول
- [ ] H0–1: اقرأ migration، تحقق من البيئة وbaseline المحفوظ، ثبّت إعداد الجودة المرجعي.
- [ ] H1–3: استخرج adapter يحمل الموديلات مرة واحدة، أزل chdir والمسارات الثابتة، أخرج WAV مع timings وcallback stages.
- [ ] H1–3: نفذ تجهيز مدخل المستخدم الحقيقي: timestamps، 25fps، 16k mono، وضبط RGB/BGR والمحاذاة.
- [ ] H3–6: دمج اختيار face_id. runner الحالي يأخذ أول كشف؛ انقل منطق اختيار الصندوق من Inference بعد المراجعة، ثم اتبع الهدف المحدد دون تبديل صامت.
- [ ] H3–6: مع Dev 2 شغّل Job من API على GPU. شغّل هدفين في فيديو واحد بالتبادل للتحقق من ربط الاختيار، ثم GT لكل هدف.
- [ ] H6–9: فقد الوجه والأخطاء والذاكرة والإلغاء بين مراحل آمنة. لا تورث landmarks قديمة عبر فقد طويل دون حد وحالة.
- [ ] H9–12: regression ووقت cold/warm، تعليمات restart وsnapshot من الإعدادات.

## جودة لا تتنازل عنها
لا تفترض أن انخفاض correlation يثبت صحة الهدف. استخدم مراجع gt5 للمقارنة، واحفظ طول الصوت والتزامن. قبول هندسي مبدئي للتحسين: تراجع SI-SDRi <=0.5 dB لكل هدف، مع فحص مستقل للهوية والحركة؛ ليس معيارًا علميًا عامًا.

## اليوم الثاني
الأولوية تصحيح مرجع إحداثيات landmarks/interpolation والقص، ثم batching للحساب إذا تدعمه المكتبة. لا تعتمد d16/l2 أو downscale افتراضيًا لأن B تدهور. زمن forward صغير؛ ركز على تجهيز الوجه.

اختبر offline-paced chunks ثم capture فعلي مع Dev 2. نافذة ثانيتين + lookahead تعني تأخيرًا خوارزميًا يجب حسابه. بوابة القرار في realtime doc. لا تعلن streaming بناءً على forward وحده.

## تسليمك للأطراف
- Dev 2: adapter موثق + الأخطاء + progress + schema timings.
- Dev 3: candidate frames/boxes وهوية ثابتة من خلال API.
- Dev 4: WAV بنفس timeline وsource_offset إن موجود.
- الملف النهائي: مقاييس كل هدف، التشغيل، حدود الأداء، ومتى يرجع baseline.

## Done
Job من المنتج يختار الوجه الحقيقي ويستخرج صوته، ويحافظ على GT المرجعي، ولا يغير cwd أو يكتب ملفات مشتركة بين الطلبات. ML optimization لا يؤخر بوابة H6.

## Adaptive face tracking (opt-in, not validated on GPU)

Status: code and unit tests exist. It has NOT been run on real footage, a GPU, or the A/B clips. The reference cadence (`tracking_mode=reference`, detect every 8, landmarks every frame) stays the default until the adoption gate passes.

Baseline from legacy measurements (RTX 3060, 14 s clip): face detection about 26 s and landmarks about 25 s of a 64 s run; the separation forward pass is about 1.7 s. Fixed thinning (detect every 16, landmarks every 2) kept A within 0.02 dB but dropped B by 6.06 dB (head cut off at the top of the frame), so B rejected it (`legacy_snapshot/reports/FOCUS_faceprep_speed_report.html`).

Enable: `FOCUS_TRACKING_MODE=adaptive` (or `AdapterConfig(tracking_mode="adaptive")`). Settings: `adaptive_min_confidence`, `adaptive_max_interval` (32), `adaptive_edge_interval` (8), `adaptive_identity_iou`, `adaptive_max_hold_frames`.

How it decides (`focus_ml/adaptive_tracking.py`):
- Light tracker (`light_tracker.py`, template matching, no weights) moves the target box between full detections.
- Full detection runs on: first frame, low confidence or no box from the light tracker, `max_interval` frames elapsed, `edge_interval` frames when the box touches the frame edge (the B case), and every frame while uncertain or lost.
- Identity guard: a detection is accepted only if it overlaps the predicted target box and clearly beats the runner-up. Otherwise the last box is held, an `uncertain` event is recorded, then `lost` after `max_hold_frames`, then `reacquired`. Each lost period is returned with start/end ms. The adapter also adds a warning per period.
- Landmarks still run per `landmark_every`; the adaptive mode does not change that yet.

Per-run report: every extraction (both modes) sets `adapter.last_tracking_report` and writes `<job_dir>/tracking_report.json` with full-detect, light-track, hold and landmark counts, stage seconds, events and loss intervals. `ExtractionResult.timings` also carries `full_detects`, `light_tracks`, `landmark_calls`, `detect_s`, `landmark_s`. The `ExtractionResult` fields themselves are unchanged.

### Measuring on the GPU machine (not Replit)

1. Reference run: `python product/tools/bench_chunks.py --video CLIP --clip-id ID --speaker a --target-slot 0 --label ref --run-dir runs/ref --tracking-mode reference` (repeat for each clip with the same `--run-dir` and `--label`; per-clip speed is kept in `run.json`)
2. Same with `--tracking-mode adaptive --label adaptive --run-dir runs/adaptive`.
3. `python -m focus_eval evaluate --dataset DATASET --run runs/ref --out reports/ref.json` (same for adaptive).
4. `python -m focus_eval gate --baseline reports/ref.json --candidate reports/adaptive.json`

The tool processes consecutive 2 s chunks, reports real-time factor (processing time / audio time, target <= 0.8), latency and queue depth, and writes the isolated audio in the eval run layout. Use A and B (and the Egyptian set once clips are ready). `gate` returns `adopt` only if no target loses more than 0.5 dB SI-SDRi (B included), nobody becomes the wrong person, no audio is lost or truncated, and RTF <= 0.8 on every evaluated clip, and output length within 0.1 s of the mixture with no silent gaps. Missing speed data for any clip or different datasets gives `inconclusive`. Do not enable adaptive mode by default on any other basis.
