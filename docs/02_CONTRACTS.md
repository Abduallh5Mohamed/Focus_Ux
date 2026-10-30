# عقد الفريق — مسودة تُثبت في الساعة الأولى

## هوية الملفات والوجوه
- video_id وjob_id عشوائيان؛ IDs ليست تفويض وصول.
- session token عشوائي يصدر عند أول رفع؛ في `Authorization: Bearer ...`، لا في URL/logs.
- face_id يطابق فيديو + candidate frame timestamp + bbox بإحداثيات الفريم الأصلي + أبعاده.
- نسخة اليوم الأول تدعم الاختيار من أول فريم صالح متوافق مع قدرة المحرك. لو المحرك مقيد بفريم البداية، اعرض هذا القيد ولا تسمح بوجه لاحق دون دعم فعلي.

## HTTP
| Method / path | المدخل | الرد |
|---|---|---|
| POST /videos | multipart file | 201 video_id, session_token إن جديد, metadata, faces_status |
| GET /videos/{id}/faces | auth | pending/ready/failed، face_id, thumbnail_url, bbox, timestamp_ms, frame_size |
| POST /jobs | video_id, client_request_id + face_id (محركات الشفاه) أو enrollment_id (audio_only، الافتراضي؛ 409 ENROLLMENT_REQUIRED بدونه) | 202 job_id؛ منع تكرار نفس الطلب |
| GET /jobs/{id} | auth | حالة الطلب والمراحل والنتائج |
| GET /jobs/{id}/audio | auth | WAV، يدعم وصول المشغل عبر fetch/blob |
| GET /jobs/{id}/transcript | auth | segments أو pending/failed |
| GET /jobs/{id}/mix | auth | sample_rate, others_available (+ سبب عدم التوفر), alignment_ms, level_gain, correlation |
| GET /jobs/{id}/mix/{voice\|others} | auth | WAV float32 على timeline الفيديو الأصلي؛ others يرجع 409 MIX_UNRELIABLE لو الطرح غير موثوق |
| POST /jobs/{id}/exports | voice_level 0..2, others_level 0..1, noise_reduction off/light/strong | 202 export_id, status=rendering؛ 409 MIX_UNRELIABLE لو others_level>0 والطرح غير موثوق |
| GET /jobs/{id}/exports/{export_id} | auth | rendering / ready / failed (+ error) |
| GET /jobs/{id}/exports/{export_id}/file | auth | video/mp4: نفس صورة الفيديو بدون إعادة ترميز + الصوت الجديد |
| GET /config | بدون auth | engine, max_video_ms, max_upload_bytes, voice_file_max_ms, min_enrollment_ms |
| GET /videos/{id}/analysis | auth | pending/ready/failed + voices: voice_id, clean_s, overlap_fraction, usable, refusal, warnings, sample, sample_url (لا vectors أبدًا) |
| POST /videos/{id}/analysis/retry | auth | يعيد التحليل لو فشل |
| GET /videos/{id}/analysis/voices/{voice_id}/sample | auth | WAV قصير (عيّنة نظيفة) |
| POST /videos/{id}/voice-suggestions · GET …/{face_id} | face_id | ترتيب الأصوات للوجه المختار: candidates (rank, suggested), evidence=on_screen\|talk_time_only, note (اقتراح فقط) |
| POST /videos/{id}/enrollments | face_id + source=voice (voice_id) أو range (start_ms,end_ms) | 202/200 enrollment_id, status, warnings؛ 422 ENROLLMENT_REFUSED لو العيّنة أقل من 4 ثواني نظيفة أو أطول من 60 ث |
| POST /videos/{id}/enrollments/upload | multipart face_id + file | نفس الرد؛ الملف يُحذف بعد التسجيل |
| GET /videos/{id}/enrollments/{eid} | auth | pending/ready/failed + error |
| DELETE /videos/{id} | auth | 202 deletion_pending أو 204 بعد الحذف |

### ميكس الصوت وتصدير الفيديو (الخادم فقط، بدون تغيير للـ worker)
- الأصوات التانية = الصوت الأصلي ناقص الصوت المعزول بعد المحاذاة (source_offset_ms ثم بحث ارتباط محدود ±200ms) ومطابقة المستوى بالمربعات الصغرى. لو الارتباط أقل من 0.3 أو التغطية أقل من 90% أو الصوت صامت يتحول إلى unreliable ولا يُستخدم أبدًا.
- تقليل الضوضاء فلتر ترددات عادي (high-pass 100Hz خفيف؛ 150Hz + low-pass 6kHz قوي)، وليس نموذج ذكاء اصطناعي.
- الإخراج محدود الذروة (limiter بسقف 0.98) فلا يحصل clipping. التصدير يتطلب ffmpeg على الخادم (`FOCUS_FFMPEG`)، ينسخ الفيديو بدون تغيير، ويفشل بـ EXPORT_UNSUPPORTED لو الصورة لا تُنسخ داخل MP4 (مثل VP8). ملفات التصدير تحت jobs/{job}/exports وتُحذف مع الفيديو.

لا ينفذ GET عملية GPU طويلة. الكشف async حيث يلزم. اخدم الصور والفيديو بنفس حماية الملكية؛ لا تحول media URLs العامة إلى تسريب ملفات. عند استخدام blob URL ألغِه عند مغادرة الشاشة.

## حالة الطلب
```json
{
  "job_id": "uuid", "status": "processing", "stage": "tracking",
  "selected_face_id": "uuid", "audio_status": "pending",
  "transcript_status": "pending", "queue_position": 0,
  "error": null, "result": null
}
```
status: queued / processing / completed / failed / cancelled.
stage: validating / preparing / matching (audio_only) / tracking / separating / transcribing / ready.
`transcript_enabled=false` لمحرك audio_only: لا تفريغ نص. `result.follow_periods`: voice_follow (الهدف) و uncertain (output_allowed=false، تُكتم في الصوت المعزول).
audio_status: pending / ready / failed. transcript_status: pending / processing / ready / failed.
يجوز تشغيل الصوت أثناء transcribing؛ status النهائي completed حتى لو transcript_status=failed والصوت ناجح.

## النص
`segments: [{id,start_ms,end_ms,text}]` على خط زمن الفيديو المعروض. فرّق بين transcript آلي وبين نص مصحح بشريًا. لا تستخرج WER مرجعيًا من نفس التفريغ ثم تدعي دقة مؤكدة.

## Python adapter الداخلي
```python
load_models(config) -> ModelBundle
detect_candidates(video_path, config) -> list[FaceCandidate]
extract_target(video_path, target, job_dir, models, on_progress) -> ExtractionResult
```
ExtractionResult يحتوي wav_path, duration_ms, source_offset_ms, timings, warnings. العقد لا يقبل مسارات يرسلها المستخدم؛ API يحول IDs لمسارات موثوقة.

## Job lifecycle
Dev 2 يحدد DB schema وclaim ذري للطلب. worker واحد يقرأ queued ويكتب المراحل. requests لا تحمل كائنات torch. عند restart لا يبقى processing إلى الأبد: علّم الطلب interrupted/failed مع retry واضح أو أعده بطريقة آمنة محدودة.

## خطأ موحد
`error: {code,message,retryable}`. أمثلة: INVALID_MEDIA, LIMIT_EXCEEDED, NO_AUDIO, FACE_NOT_FOUND, TARGET_LOST, GPU_BUSY, PROCESSING_FAILED. لا traceback أو مسار نظام للمستخدم.

## Mocks
احفظوا responses متفقًا عليها في contracts/fixtures. تعرض الواجهة تنبيه dev mock في التطوير؛ builds العرض الحقيقية لا تستخدم نتائج وهمية. المثال الجاهز مسمى بوضوح.


## محرك audio_only وبروتوكول الـ worker
- الافتراضي `FOCUS_ISOLATION_ENGINE=audio_only`؛ محركات الشفاه (dolphin…) متاحة ويبقى حدها 15 ث (يُفرض عند إنشاء الطلب). حد الرفع الافتراضي 180000ms و200MB (`FOCUS_MAX_VIDEO_MS`, `FOCUS_MAX_UPLOAD_BYTES`).
- بعد التحويل يعمل كشف الوجوه وتحليل الصوت (diarization + voiceprints + عيّنات نظيفة) بالتوازي؛ النتيجة تُخزن لكل فيديو وتُستخدم في التسجيل والاستخراج. voiceprint للطلب فقط ويُحذف مع الفيديو.
- مهام الـ worker الجديدة (نفس مفتاح الـ worker وحدود الحجم والتحقق): `analyze` → POST /worker/tasks/{id}/analysis؛ `enroll` → …/enrollment (voiceprint أو refused)؛ `visibility` → …/visibility (يستلم الفيديو وقت التسجيل فقط)؛ `isolate` → …/regions ثم …/audio (header `X-Focus-Engine: audio_only`). مهام analyze/enroll/isolate تنقل صوتًا فقط: لا إطارات ولا وجوه ولا بيانات شفاه بعد التسجيل. مهمة واحدة لكل نوع في نفس الوقت.
- الاقتراح من ظهور الوجه على الشاشة وقت التسجيل فقط، ولا يؤكد الهوية؛ المستخدم يؤكد بالاستماع.
