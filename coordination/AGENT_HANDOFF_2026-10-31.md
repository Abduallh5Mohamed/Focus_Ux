# تسليم لمهندس/أيجنت تاني — FOCUS (عزل صوت متكلم من فيديو)

آخر تحديث: 2026-10-31 04:35 (GMT+2)
الـ worktree: `C:\Users\abdua\WorkBuddy\Worktrees\Focus_Ux\main-0aec6d07`

---

## 1) المشروع بيعمل إيه

**FOCUS** = PWA: المستخدم يرفع فيديو → يختار المتكلم → الخدمة تعزل صوته لوحده → يسمع مقارنة أصل/معزول → ينزّل MP4.

- المعالجة على الجهاز/السيرفر (GPU على جهاز الـ D:)، مش في المتصفح.
- الرقم المرجعي في الخطة: SI-SDRi حوالي +17.6 / +8.4 dB على تسجيلات مصرية.
- المرجع: `docs/00_MASTER_PLAN.md`، `docs/05_VOICE_FOLLOW.md`، `docs/VOICE_PIPELINE.md`.

## 2) المعمارية

```
product/
  apps/web/            React + Vite (PWA)
  services/api/        FastAPI: upload, faces, analysis, enrollments, jobs, exports
    focus_api/dispatcher.py   طابور مهام (thread واحد) + face detection + analysis + jobs
    focus_api/inference.py    InferenceProviders: يلفّ الـ engine
    focus_api/mix.py          level fit + render
  services/worker/     Job model
  packages/ml/focus_ml/  كل الـ ML
    voice/             diarizer, embedder, match, extractor, engine, music, separation
    normalize.py       الكانونيكال (ffmpeg)
```

### المحركين

| المحرك | إزاي يختار المتكلم | ملاحظات |
|---|---|---|
| `dolphin` (lip) | تتبع وش + حركة شفايف | محتاج موديلات Dolphin (مش موجودة على الجهاز الحالي) |
| `audio_only` | diarization + بصمة صوت | المسار اللي شغالين عليه |

### الموديلات

| الموديل | الدور | مكانه |
|---|---|---|
| `pyannote/speaker-diarization-community-1` | مين بيتكلم امتى | `A:/Focus_runtime/voice/weights/` |
| `speechbrain/spkrec-ecapa-voxceleb` | بصمة الصوت | نفس المكان |
| ClearerVoice `MossFormer2_SS_16K` | **فصل صوتين** | `A:/Focus_runtime/clearervoice/checkpoints/` |
| Demucs `htdemucs` | فصل موسيقى | `A:/Focus_runtime/venvs/demucs-venv` (اتضح إنه مش مفيد هنا) |
| Dolphin + YOLO | كشف الوش/الشفايف | **غير موجود** على الجهاز |

## 3) البيئات (كلها على A: لأن C: مليان)

| الغرض | المسار |
|---|---|
| python لكل حاجة (torch, pyannote, speechbrain, clearvoice, fastapi) | `A:/Focus_runtime/cv-venv/env/Scripts/python.exe` |
| venv للاختبارات (pytest, fastapi, soundfile, numpy) | `A:/Focus_runtime/venvs/analysis-venv/env/Scripts/python.exe` |
| venv الديموكس | `A:/Focus_runtime/venvs/demucs-venv/env/Scripts/python.exe` |
| أوزان الصوت | `A:/Focus_runtime/voice` |
| أوزان ClearerVoice | `A:/Focus_runtime/clearervoice` |
| تخزين الـ API | `A:/Focus_runtime/app-storage` |

**مهم:** الـ engine بيدوّر على `ffmpeg` بالاسم في الـ PATH. فيه شيم على `runtime/bin/ffmpeg.exe` — لازم يتضاف للـ PATH وإلا التحليل يفشل بـ "audio tool unavailable".

## 4) تشغيل المشروع

```bash
bash runtime/analysis/start_focus.sh
# Web :5000  ->  API :8000  (mode=local, engine=audio_only, extractor=separation)
```

أو يدوي:
```bash
cd product
export PATH="$PWD/../runtime/bin:$PATH"
export PYTHONPATH="$PWD/packages/ml;$PWD"
export FOCUS_INFERENCE_MODE=local FOCUS_ISOLATION_ENGINE=audio_only FOCUS_VOICE_EXTRACTOR=separation
export FOCUS_CLEARERVOICE_PYTHON="A:/Focus_runtime/cv-venv/env/Scripts/python.exe"
export FOCUS_CLEARERVOICE_HOME="A:/Focus_runtime/clearervoice"
export FOCUS_VOICE_HOME="A:/Focus_runtime/voice"
export FOCUS_API_STORAGE_ROOT="A:/Focus_runtime/app-storage"
A:/Focus_runtime/cv-venv/env/Scripts/python.exe -m uvicorn services.api.focus_api.main:app --port 8000
```

الاختبارات:
```bash
cd product
PATH="/c/Users/abdua/WorkBuddy/Worktrees/Focus_Ux/main-0aec6d07/runtime/bin:$PATH" \
A:/Focus_runtime/venvs/analysis-venv/env/Scripts/python.exe -m pytest tests/voice tests/ml tests/api -q
# آخر نتيجة: 243 passed, 1 failed (ffprobe مش موجود), 1 skipped (torch)
```

---

## 5) الأخطاء المطلوب إصلاحها — مرتبة بالأولوية

### 🔴 P0 — الـ dev server بيرجع 404 على كل رفع
**العرض:** المستخدم يرفع فيديو → "مش لاقيين الطلب ده. ممكن يكون اتحذف." (NOT_FOUND) مع إن الـ API شغال.

**السبب:** `API_BASE_URL = ''` افتراضيًا في `apps/web/src/lib/env.ts`، فالواجهة بتعمل `POST /videos` من غير بادئة `/api`، والـ vite معمل proxy لـ `/api` بس → الطلب بيروح لسيرفر الـ dev ويرجع 404.

**الدليل:** لوج الـ API كان **صفر طلبات** من المتصفح (كل اللي فيه طلباتي أنا).

**الحل الحالي (مؤقت):** `product/apps/web/.env.local` فيه `VITE_API_BASE_URL=/api` (وهو في `.gitignore`).

**المطلوب:** إصلاح دائم — يا إما `vite.config.ts` يعمل proxy لـ `/videos`, `/jobs`, `/config`, `/healthz`, `/worker-kit.zip`، يا إما الـ default في `env.ts` يبقى `/api` في وضع `DEV`. + اختبار.

---

### 🔴 P1 — جودة الصوت الناتج وحشة (شكوى المستخدم الأساسية)
"الاوتبوت طلع زبالة". الأرقام بتقول تحسّن كبير، فالمشكلة على الأغلب **artifacts** مش نسبة الخلفية:

| | كلام | فراغ | الفرق |
|---|---|---|---|
| الأصل | -12.2 | -12.7 | 0.5 dB |
| الـ export الحالي | -11.9 | -18.4 | **6.6 dB** |
| `isolated.wav` من الـ job | -28.9 | -38.8 | **9.9 dB** |
| الديمو (دون تصدير) | -13.6 | -25.0 | 11.4 dB |

فرضيات مرتبة:
1. **الـ export بيضيّع 3.3 dB** من 9.9 → 6.6. راجع `services/api/focus_api/mix_service.py` و`mix.render_mix` — يمكن `noise_reduction` الافتراضي أو الـ level fit بيرفع الفراغات.
2. **artifacts من MossFormer2_SS**: الموديل بيشتغل على 16 kHz، والصوت بيرجع مرفوع لـ 48 kHz. لازم قياس موضوعي (SI-SDR / PESQ / ViSQOL) مش بس مستويات.
3. **الـ gate + floor**: `out = gate*chosen + (1-gate)*floor*other` بـ floor = -12 dB. لو الـ floor عالي أوي، الخلفية بترجع في الفراغات. جرّب -18/-24.
4. **تقطيع في الأطراف**: `fade_ms=30`, `bridge_ms=250` في `voice/extractor.py::target_mask` — جرّب قيم تانية.
5. **الـ 8 kHz ceiling**: موديل 16k، مش مشكلة قابلة للحل بالـ resampling — محتاج موديل 48k لو الجودة مهمة.

**المطلوب:** قياس موضوعي قبل/بعد + قرار. الأدوات: `runtime/analysis/speech_sep_demo.py` و`integration_full.py` موجودين كأساس.

#### قياس فعلي على مخرج المستخدم (job `cb182e5e361e4c6a875c57b305e44cb3`، 14.87 ثانية)

الملف: `A:/Focus_runtime/app-storage/jobs/cb182e5e361e4c6a875c57b305e44cb3/isolated.wav`

| مقياس | القيمة | المعنى |
|---|---|---|
| RMS / peak | **-31.2 / -13.6 dBFS** | ناتج **هادي جداً** (13 dB headroom) |
| frame RMS p10 / p50 / p90 | -67.0 / -38.4 / -26.3 | مدى ديناميكي واسع |
| **قفزات >20 dB بين فريمات 20ms** | **22 قفزة = 1.5/ثانية** | **pumping / طقطقة** |
| **قفزات >12 dB** | **75 قفزة = 5/ثانية** | تقطيع مسموع |
| أصفار تامة | 5.17% | الموديل بيسكّت فريمات → قطع حاد |
| توزيع الطاقة | **0–1kHz: 60.7%** / 1–4kHz: 32.8% / **4–8kHz: 6.5%** | **الصوت مكتوم/تليفوني** |

**الاستنتاج:** "زبالة" = **٣ أسباب قابلة للقياس**، مش إحساس:
1. **صوت مكتوم** — سقف 8 kHz (موديل 16k) + 60% من الطاقة تحت 1 kHz → محتاج موديل 48k أو على الأقل de-emphasis/إكوالايزر تعويضي.
2. **pumping/طقطقة** — 5 قفزات >12 dB في الثانية عند حدود الـ gate + 5.17% أصفار تامة. الحل: fade أطول (150–300ms)، bridge أطول، ومنع الأصفار التامة (mix مع floor صغير بدل gate=0).
3. **مستوى واطي** — -31 dBFS RMS: محتاج LUFS normalization (-16 LUFS مثلاً) قبل التصدير.

الترتيب المقترح للإصلاح: (2) الأول لأنه أوضح إحساس، بعده (3)، وبعدين (1).


---

### 🟠 P2 — مسار audio_only لازمه face (تصميم غلط)
`service.create_enrollment` بيدوّر على الـ face في الداتابيز قبل ما يقبل الـ enrollment، والمحرك audio_only مش بيستخدم وش أصلاً.

**اللي عملته:** في `dispatcher._detect_faces`، لو `settings.audio_only` وكشف الوجوه فشل، بحط face واحد placeholder `audio-only` وحالة `ready` بدل `failed` (عشان الواجهة متقفلش على جهاز مفيهوش موديلات lip). + اختبار `test_audio_only_keeps_one_placeholder_when_face_detection_fails`.

**المطلوب:** قرار — إما نبني الـ audio_only من غير face خالص (الأصح)، أو نسيبه كده ونوثّقه.

---

### 🟠 P3 — اختبارات ناقصة بسبب ffprobe
`tests/api/test_export.py::test_export_is_in_sync_and_video_unchanged` بيفشل: `FileNotFoundError: ffprobe`. الـ `imageio-ffmpeg` بيجيب `ffmpeg` بس. محتاج ffprobe في الـ PATH أو skip واضح.

---

### 🟡 P4 — الأداء
18 دقيقة لـ 137 ثانية على CPU (≈8× المدة). على GPU لازم يتقاس. المسار ده مش realtime.

---

### 🟡 P5 — Demucs (مسار ميت)
`focus_ml/voice/music.py` + `FOCUS_VOICE_EXTRACTOR=music` موجودين وشغالين، بس **مش مفيد** على الفيديو ده: الـ vocals stem طلع 99.4% من الطاقة (الخلفية صوت بني آدم مش موسيقى). سيبهم كخيار للموسيقى الحقيقية، متفعّلهمش افتراضي.

---

## 6) الملفات المعدّلة/المضافة في الشغل ده

```
M product/packages/ml/focus_ml/normalize.py          # fps=None => stream copy بدل re-encode 30->25
M product/packages/ml/focus_ml/voice/engine.py       # صوت واحد => بناء mask من diarization
M product/packages/ml/focus_ml/voice/extractor.py    # DuckedBaseline + choices (ducked/gated/music/separation)
M product/services/api/focus_api/inference.py        # audio_only بيستخدم fps=None
M product/services/api/focus_api/mix.py              # level fit
M product/services/api/focus_api/dispatcher.py       # placeholder face لو الكشف فشل في audio_only
M product/apps/web/vite.config.ts                    # FOCUS_API_TARGET + FOCUS_WEB_PORT
M product/tests/voice/test_audio_engine.py
?? product/packages/ml/focus_ml/voice/music.py
?? product/packages/ml/focus_ml/voice/separation.py
?? product/tools/demucs_separate.py, demucs_setup.py
?? product/tools/clearervoice_separate.py, clearervoice_setup.py
?? product/tests/voice/test_music_extractor.py, test_speech_separation.py, test_extractor_ducked.py
?? product/tests/api/test_mix_level_fit.py
?? product/apps/web/.env.local                        # VITE_API_BASE_URL=/api  (gitignored)
```

الـ handoff التفصيلي: `coordination/WORKBUDDY_HANDOFF_AUDIO_FIX.md`
الأدلة الرقمية: `runtime/analysis/{demucs_findings,integration_canonical,integration_api,integration_full,speech_sep_metrics}.json`

## 7) قيود الجهاز الحالي

- **C: مليان** (~1.5 GB فاضي). كل حاجة تقيلة على A:.
- **موديلات الوش مش موجودة** → مسار الـ lip غير قابل للاختبار هنا خالص.
- الرام بتخلص بسرعة؛ pyannote بيرمي `DefaultCPUAllocator: not enough memory: 327 MB` لو الذاكرة ضيقة.
- فيديو المستخدم المرجعي: `C:/Users/abdua/Downloads/ssstik.io_1793296206879.mp4` (137 ثانية، 576×1024، 30 fps، فيه متكلم + صوت تاني تحت كلامه).
