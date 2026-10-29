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
| POST /jobs | video_id, face_id, client_request_id | 202 job_id؛ منع تكرار نفس الطلب |
| GET /jobs/{id} | auth | حالة الطلب والمراحل والنتائج |
| GET /jobs/{id}/audio | auth | WAV، يدعم وصول المشغل عبر fetch/blob |
| GET /jobs/{id}/transcript | auth | segments أو pending/failed |
| DELETE /videos/{id} | auth | 202 deletion_pending أو 204 بعد الحذف |

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
stage: validating / preparing / tracking / separating / transcribing / ready.
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
