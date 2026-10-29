# Dev 2 — API وQueue والتخزين والنشر

## ملكيتك
services/api، infra، schema SQLite، contracts بعد مراجعة الجميع. worker implementation مع Dev 1.

## اليوم الأول
- [ ] H0–1: ثبّت العقود وfixtures والمتغيرات والـerror codes.
- [ ] H1–3: رفع مع حدود حجم ومدة ونوع فعلي عبر ffprobe؛ IDs ورموز وصول؛ مجلد منفصل لكل upload/job.
- [ ] H1–3: SQLite بحالات Job وانتقالات واضحة، claim ذري، Queue صغيرة بحد معلن، منع تكرار زر الإرسال بـclient_request_id.
- [ ] H3–6: worker متصل، progress حقيقي، media endpoints محمية، polling. اختبر وصول API من نت آخر مبكرًا.
- [ ] H6–9: faster-whisper/ASR الحالي في مرحلة مستقلة؛ النص بعد الصوت، وGPU scheduling يمنع OOM. segments بتوقيت صحيح.
- [ ] H6–9: تنزيل وحذف وإلغاء آمن، retention 24h مبدئيًا، cleanup job وretry محدود.
- [ ] H9–12: HTTPS/CORS على origin الواجهة، rate limit وحدود queue، restart recovery، اختبار طلبين دون اختلاط.

## إعداد تشغيل بسيط
API وDB وworker على جهاز GPU الحالي. عملية worker واحدة؛ لا تجعل uvicorn multi-worker يحمل الموديل مرات متعددة. واجهة static على Pages وAPI عبر tunnel. لا تنقل ملفات الفيديو عبر Pages Functions.

## التحقق والأمان العملي
العميل يرسل IDs لا مسارات filesystem. لا shell=True مع أسماء المستخدمين. media probe بمهلة، وتنظيف الملف عند فشل التحقق. رموز الوصول لا تدخل logs/URLs. CORS لا يغني عن authorization.

لا تبقِ upload request مفتوحًا طوال inference. POST يرجع job_id ثم polling. Quick Tunnel لا يدعم SSE؛ الرابط قد يتغير ومفيش uptime مضمون.

## اليوم الثاني
راجع deployment والضغط المحدود وhealth. شارك Dev 1 في جلسة chunks بهوية session، sequence_id، capture timestamps وإعادة ترتيب ومنع تكرار. لا تفترض chunks الحاوية قابلة لفك منفصل. queue bounded؛ عند التخلف وضح overload وأوقف/حوّل لتسجيل ثم معالجة، لا تحذف عينات بصمت.

## Done
API متاح من جهاز خارجي، job بعد restart لا يظل عالقًا، تنزيل وحذف يعملان، لا تسريب بين sessions، والصوت يصل حتى لو ASR فشل. سلّم env.example وrunbook دون أسرار.
