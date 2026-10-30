# مجموعة الاختبار المصرية — FOCUS

قالب لـ 10 مقاطع. كل المقاطع حاليًا `status: "template"` وبالتالي **لا تُحتسب** في أي تقرير. الأداة تقيّم ملفات موجودة فقط؛ لا تشغّل المحرك ولا GPU ولا ASR.

## السيناريوهات

| الوسم | العدد | المطلوب في المقطع |
|---|---|---|
| `baseline` | 2 | متكلمان، وشان واضحان وثابتان |
| `head_motion` | 2 | حركة راس أو الشخص قريب من حافة الإطار |
| `face_disappears` | 2 | وش الهدف يختفي أو يتغطى أثناء الكلام |
| `similar_voices` | 2 | متكلمان بنفس الجنس وطبقة صوت متقاربة |
| `overlap` | 2 | كلام متداخل لعدة ثوانٍ (واحد منهم مع حركة راس) |

المدة المقترحة 10–15 ثانية لكل مقطع، حسب حدود المنتج (15 ثانية / 50MB).

## إضافة مقطع

1. أنشئ `clips/<clip_id>/` وضع فيه:
   - `mix.wav`: الخلطة التي تدخل النموذج (WAV PCM، أي معدل عينات؛ الأداة تحوّله إلى 16kHz mono).
   - `<speaker>_ref.wav`: تسجيل نظيف لكل متكلم على نفس الخط الزمني للخلطة.
   - `video.mp4`: الفيديو المصاحب (اختياري للقياس، مطلوب للتشغيل الفعلي).
   - `<speaker>.txt`: النص المرجعي **المكتوب يدويًا** لكل هدف.
2. في `manifest.json` غيّر `status` إلى `"ready"` واملأ `source` (الوصف، الرابط، الرخصة، من سجّل المقطع) و`targets`.
3. `transcript_status`:
   - `human_verified`: كتبه أو راجعه شخص مصري. هذا فقط ما يدخل في أرقام CER/WER الرئيسية وبوابة التراجع.
   - `provisional_asr`: ناتج تفريغ آلي. يُحسب في خانة منفصلة "مبدئي" ولا يُعتبر نتيجة نهائية.
4. شغّل `validate`. أي مقطع `ready` ناقصه ملف أو رخصة يمنع `evaluate`.

لا تنزّل مقاطع من الإنترنت بدون موافقة الفريق على المصدر والرخصة. ملفات الصوت والفيديو في `clips/` مستبعدة من Git؛ خزّنها في مساحة مشتركة أو App Storage.

## التشغيل

من جذر المشروع (يحتاج `numpy` فقط):

```bash
export PYTHONPATH=product/packages/eval
python -m focus_eval validate  --dataset product/datasets/egyptian_eval
python -m focus_eval evaluate  --dataset product/datasets/egyptian_eval --run runs/before --out reports/before.json
python -m focus_eval evaluate  --dataset product/datasets/egyptian_eval --run runs/after  --out reports/after.json
python -m focus_eval compare   --baseline reports/before.json --candidate reports/after.json
```

`compare` يخرج بكود 0 عند النجاح، و1 عند أي تراجع، و3 (غير حاسم) إذا اختلفت مجموعتا الاختبار أو لم يُقَس أي هدف في التقريرين معًا — لا يُعتبر ذلك نجاحًا. العتبات: `--si-sdri-drop-db` (افتراضي 0.5)، `--cer-increase` (افتراضي 0.02 مطلقة)، `--include-provisional`.

## شكل مخرجات التشغيل (`--run`)

```
runs/before/run.json            {"label": "baseline d8/l1"}   (اختياري)
runs/before/<clip_id>/<speaker>.wav   الصوت المعزول لهذا الهدف
runs/before/<clip_id>/<speaker>.txt   النص الناتج (اختياري؛ غيابه يظهر كـ missing_hypothesis)
```

**القياس الحقيقي (تشغيل المحرك وإنتاج هذه المخرجات) يتم على جهاز الـ GPU**؛ Replit لا يوفر GPU ولا أوزان النماذج. الأداة هنا تحسب فقط.

## المقاييس

- **الشخص الغلط:** الصوت المعزول يُقارَن (SI-SDR بعد المحاذاة) بمرجع كل متكلم في المقطع. إن كان الأقرب غير الهدف يُحسب خطأ. `rate = wrong / evaluable` (المقاطع ذات متكلم واحد غير قابلة للقياس). `margin_db` الفرق بين مرجع الهدف وأقرب مرجع آخر؛ أقل من 3dB يُعلّم `ambiguous`.
- **CER/WER:** بعد توحيد الكتابة: حذف التشكيل والتطويل وعلامات الترقيم، أ/إ/آ/ٱ←ا، ى←ي، ة←ه، الأرقام العربية←ASCII. CER يتجاهل المسافات (حدود الكلمات يغطيها WER). المعدلات الكلية = مجموع الأخطاء / مجموع طول المرجع.
- **SI-SDRi:** SI-SDR للناتج ناقص SI-SDR للخلطة، كلاهما بعد محاذاة زمنية ±50ms (مأخوذ من `legacy_snapshot/tools/align_eval.py`). `lag_edge` يعني أن الإزاحة على حد نافذة البحث والنتيجة غير موثوقة.

حدود: SI-SDR يقارن بالمراجع النظيفة، فيفترض أن المراجع على نفس التوقيت ونفس مستوى الإعداد المستخدم في بناء الخلطة. أرقام اختبار الوحدات مبنية على إشارات اصطناعية ولا تثبت أداء النموذج.

## وسوم إضافية للحالات الحدّية
`whisper`, `shout`, `noise`, `reverb`, `no_solo_enrollment`: مقاطع حقيقية لقسم "القيود" في التقرير النهائي. غيابها يظهر كـ `no_clips` وليس كنجاح.

## التقييم النهائي بأمر واحد
```bash
python product/tools/final_eval.py --dataset product/datasets/egyptian_eval --out reports/final --listening-seed 7
```
على لابتوب RTX 3050 فقط. التفاصيل في `docs/SPEED_AND_FINAL_EVALUATION.md`.
