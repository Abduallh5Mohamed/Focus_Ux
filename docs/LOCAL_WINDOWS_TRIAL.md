# تجربة Windows محلية — من غير لمس النسخة القديمة

الوجهة الحالية: **https://github.com/Abduallh5Mohamed/Focus_Ux — فرع `main`**.
دي تجربة على جهازك، مش نشر عام. موديلات الجهاز مش موجودة في المستودع.
نتائج فحص النسخة: [LOCAL_TRIAL_VERIFICATION.md](LOCAL_TRIAL_VERIFICATION.md).
الوضع المباشر يفضل `internal_only`؛ نجاح اختبارات الكود مش قبول للـGPU أو الكاميرا.

## 1. المتطلبات

- Git، Node.js **22.12 أو أحدث من سلسلة 22** مع npm، Python **3.12** مستقل،
  و[uv](https://docs.astral.sh/uv/getting-started/installation/).
  الأمر `py -3.12 --version` لازم ينجح. تثبيت أدوات التجربة ما يكونش جوه بيئة ML القديمة.
- `ffmpeg` و`ffprobe` متاحين في PATH لكل النوافذ، مع H.264/AAC وVP8/Opus.
  افحص `ffmpeg -version` و`ffprobe -version`.
  لو عندك نسخة بالفعل، ضيف مجلد `bin` للـPATH في نوافذ التجربة فقط بدل استبدالها.
- الأصل الموجود بالفعل: `A:\focus\.venv\Scripts\python.exe` و`A:\focus\Dolphin`
  (خصوصًا `Inference.py` و`assets\20words_mean_face.npy`)، والكاش الكامل
  `A:\focus\cache\hf` و`A:\focus\cache\torch`.
  وجود أسماء المجلدات مش دليل على اكتمال الأوزان.
- NVIDIA driver شغال ومتوافق مع PyTorch في البيئة القديمة.
  **مفيش تثبيت pip أو تحديث CUDA أو تنزيل أوزان في البيئة القديمة.**

افحص من PowerShell:

```powershell
nvidia-smi
& 'A:\focus\.venv\Scripts\python.exe' -c 'import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.is_available()); torch.cuda.is_available() and print(torch.cuda.get_device_name(0))'
```

لو CUDA مش متاحة، وقف وابعت رسالة الخطأ غير السرية؛ ما تجربش إصلاح البيئة الأصلية تلقائيًا.
المصدر والأوزان بتتستخدم مكانها، من غير نسخ أو تدريب. الاتصالات الخاصة بتنزيل أصول
العزل مقفولة؛ بعض المكتبات ممكن تكتب cache metadata في الكاش الموجود.

## 2. نسخة منفصلة والتثبيت

اختار مجلد جديد فاضي، مش `A:\focus` ولا فولدر شغال قديم:

```powershell
git clone --branch main https://github.com/Abduallh5Mohamed/Focus_Ux.git A:\FocusLocalTrial
cd A:\FocusLocalTrial
git rev-parse HEAD
uv sync --locked --python 3.12 --no-python-downloads
npm --prefix product/apps/web ci
```

لو عملت clone للتجربة قبل كده، ومن غير تغييرات محلية:

```powershell
cd A:\FocusLocalTrial
git status --short
git pull --ff-only origin main
git rev-parse HEAD
uv sync --locked --python 3.12 --no-python-downloads
npm --prefix product/apps/web ci
```

قارن `HEAD` بمعرّف النسخة اللي اتبعت لك. لو الفرع اتحرك، لتجربة نفس النسخة استخدم
`git switch --detach <معرف-النسخة>` في **نسخة التجربة النظيفة فقط**؛ مفيش reset ولا force.
لو المستودع محتاج صلاحية، استخدم تسجيل دخول Git المعتمد عندك؛ متحطش token في URL أو الشات.
`uv` بينزّل اعتماديات API فقط في `.venv` الجديدة؛ مش بينزّل أوزان.
ماتشغّلش `scripts/run-replit.sh` على Windows.

### فحص الجاهزية قبل التشغيل

من مجلد التجربة، بعد تثبيت الاعتماديات:

```powershell
.\.venv\Scripts\python.exe product\tools\trial_readiness.py --focus A:\focus --test-uploads
```

الأداة بتفحص إصدارات الأدوات، وجود الأصول والكاش، واستيراد اعتماديات API،
وتفحص CUDA باستخدام Python القديمة للقراءة فقط. اختبارات الرفع بتشتغل
بـPython التجربة المنفصلة. مفيش تثبيت أو تنزيل أوزان أو تغيير في البيئة القديمة.
الناتج JSON غير سري فيه معرّف النسخة ونتائج الفحوص؛ الكود 2 يعني فيه فحص فشل
أو اتمنع. وجود مجلدات الكاش مش إثبات إن الأوزان كاملة.

لو هتختبر البث المستمر الجديد، ضيف `--require-continuous`. الفحص ده بيطلب وجود
مصدر البث وأداة قياسه في النسخة المدموجة؛ فشله معناه إن نسختك لسه مش جاهزة
لاختبار المسار الجديد. ما تنسخش تنفيذ يدوي مكان شغل جاهز في مهمة منفصلة.

حتى لو `ready_for_manual_trial` طلعت `true`، ده **مش** اجتياز للجودة أو التأخير:
القيمتين `gpu_inference_acceptance` و`camera_latency_acceptance` بيفضلوا
`not_measured` لحد تجربة الرفع والكاميرا الفعلية.

## 3. شغّل 3 نوافذ PowerShell من فولدر التجربة

اقفل عامل GPU القديم لو شغال قبل تجربة العامل المحلي، عشان ما يحملوش نفس الـGPU مرتين.
كل الخوادم هنا مربوطة بـloopback فقط؛ مفيش حاجة تفتح للإنترنت أو للشبكة المحلية.

**أ — API ببيئة منفصلة، وعامل حقيقي مطلوب:**

```powershell
cd A:\FocusLocalTrial
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local-api.ps1
```

`Bypass` للعملية دي بس، مش تغيير سياسة الجهاز. السكريبت بيشغّل API واحدة على
`127.0.0.1:8000`، من غير reload. `FOCUS_INFERENCE_MODE=remote` هنا معناه
عامل منفصل **على نفس جهازك**، مش خادم سحابي ولا mock.
لو فيه منفذ مستخدم، وقف النسخة المكررة بدل تغيير الأرقام عشوائيًا.

المفتاح المحلي الجديد بيتعمل من غير طباعة في
`%LOCALAPPDATA%\FocusLocalTrial\worker-token`، وبيفضل ثابت مع إعادة التشغيل.
مش بيقرأ أو يغير مفتاح Replit القديم أو مفتاح دخول الـpreview.
الـSQLite والميديا والنتائج في `%LOCALAPPDATA%\FocusLocalTrial\api`،
بعيد عن Git. استخدم حساب Windows خاص بيك، مش فولدر مشترك أو OneDrive،
ومشاركة الجهاز/النسخ الاحتياطي ممكن تكشف الملفات؛ امسح التجارب من الواجهة بعد الانتهاء.
ماترفعش المجلد ده، مفاتيحه، تسجيلاتك أو ملفات `.env` للمستودع.

**ب — الواجهة مع proxy للـAPI الحقيقية:**

```powershell
cd A:\FocusLocalTrial
$env:VITE_API_BASE_URL='/api'
$env:VITE_DEV_MOCK_API='0'
$env:VITE_LIVE_ENABLED='0'
npm --prefix product/apps/web run dev -- --host 127.0.0.1 --port 5000
```

افتح **http://127.0.0.1:5000** في Chrome/Edge. العنوان ده localhost موثوق للكاميرا.
الـproxy بيحوّل `/api/*` للـAPI على 8000. متفتحش الموقع من IP الشبكة.

**ج — فحص الاتصال ثم عامل الـGPU، باستخدام Python الأصلية بلا تثبيت:**

```powershell
cd A:\FocusLocalTrial
& 'A:\focus\.venv\Scripts\python.exe' product\tools\windows_worker.py --local-api --check
& 'A:\focus\.venv\Scripts\python.exe' product\tools\windows_worker.py --local-api --focus A:\focus
```

الاختيار `--local-api` بيسمح بعنوان واحد فقط `http://127.0.0.1:5000`، من غير
HTTP proxy موروث، ولسه بيرفض redirects. من غير الاختيار ده، HTTPS يفضل إجباري زي الأول.
العامل بيضبط `FOCUS_MODEL_SOURCE=A:\focus\Dolphin` و`FOCUS_MODEL_CACHE=HF_HOME=A:\focus\cache\hf`
و`TORCH_HOME=A:\focus\cache\torch` وoffline flags. لو التثبيت القديم في مكان تاني،
استخدم `--focus <مجلد-الأصل>` بعد التحقق من نفس البنية، مش نقل الأصول.
انتظر `Models loaded`، وافحص http://127.0.0.1:5000/api/healthz:
ظهور اتصال العامل مش دليل جودة. عدم وجود موديلات أو انقطاعه يفشل بصراحة، مفيش صوت بديل وهمي.
النص منفصل عن الصوت؛ ASR يحتاج أصل cached و`faster-whisper` موجودين بالفعل،
وفشله مش معناه إن العزل نفسه فشل. مفيش تنزيل موديل ASR مطلوب للتجربة دي.

محركات عزل بديلة للحالات الصعبة (اختيارية): [ISOLATION_ENGINES.md](ISOLATION_ENGINES.md).

## 4. اختبر الرفع الأول

1. ارفع فيديو غير حساس من 5–15 ثانية، أقل من 50 MB، فيه شخصين بيتكلموا.
2. استنى صور الوجوه، اختار الشخص المطلوب (يفضل مش أول وجه).
3. شغّل الصوت المعزول، وقارنه بالأصل: الهوية، الكلام غير المرغوب، التشويش، والتزامن.
4. جرّب فتح نتيجة في جلسة/متصفح خاص مختلف: الوصول للميديا لازم يتمنع.
5. لو الرفع فشل، وقف هنا وابعت الخطأ؛ ما تبدأش اختبار مباشر فوق عزل مش شغال.

## 5. فعّل المباشر للتجربة فقط، وبسماعات

وقف API والواجهة بـCtrl+C، وسيب العامل واقف لحد ما الخادم يرجع.
شغّل النافذة أ بنفس الأمر مع `-Live`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local-api.ps1 -Live
```

وفي النافذة ب غيّر `$env:VITE_LIVE_ENABLED='1'` وشغّل نفس أمر npm.
ده بيفعّل `FOCUS_LIVE_ENABLED=1` و`VITE_LIVE_ENABLED=1` **محليًا بس**؛ الافتراضي مقفول.
ابدأ العامل تاني بالنافذة ج، وافتح http://127.0.0.1:5000/live.

- استخدم سماعات لتجنب feedback، واسمح بالكاميرا والمايك، واختار الشخص بدري.
- سجّل **60 ثانية على الأقل**، مع حركة رأس واختفاء الوجه كام ثانية.
- اضغط Stop، اتأكد لمبة الكاميرا قفلت، واستنى المعالجة النهائية ولوحة القياس.
- اسمع النتيجة وقارن نفس المحتوى بمسار الرفع. الرفع العادي محدود بـ15 ثانية:
  استخدم مقتطفًا مطابقًا قصيرًا من محتوى الاختبار، أو تجهيز المقارنة المعتمد في مهمة القياس،
  مش رفع تسجيل الـ60 ثانية كله وتوقع قبوله.
- اختفاء الوجه لازم يظهر `target_lost`، والضغط الزائد يظهر بوضوح، مش إسقاط صوت صامت.
  أي تحذير عن قياسات غير محفوظة يعني الأرقام ناقصة، مش نجاح.

اختبار ملف بسرعة الوقت الأصلي (اختياري، بعد نجاح الرفع):

```powershell
.\.venv\Scripts\python.exe product\tools\live_gate.py --api http://127.0.0.1:8000 --video C:\TrialMedia\clip-60s.mp4
```

الأداة دي بتقيس الخادم فقط؛ **مش** capture-to-play لأنه مفيش تشغيل صوت بالمتصفح.
ماتشغّلهاش بالتوازي مع جلسة كاميرا.

## ابعت إيه، وإمتى نقول نجح؟

ابعت معرّف Git، إصدارات GPU/driver/PyTorch/CUDA، نتيجة smoke الرفع واختيار الوجه،
مدة الجلسة وعدد المقاطع، **RTF، capture-to-play median/p95، max queue depth**،
عدد المقاطع المفقودة/المكررة/غير الصالحة وحالات `target_lost/uncertain`،
أي انتقال لـrecord-then-process، وملاحظات الهوية/الجودة/التزامن مقارنة بالرفع.
ابعت نصوص الأخطاء بعد إزالة المفاتيح وAuthorization والمسارات الشخصية وsession tokens؛
ما تبعتش تسجيلات شخصية، HAR، قاعدة بيانات أو ملفات مفاتيح.

الحدود: RTF ≤0.8، p95 ≤3 ث، جلسة ≥60 ث، لا نمو queue ولا fallback بسبب الضغط،
مع مراجعة الجودة على نفس المحتوى. دي شروط تجربة، مش وعد بملاءمة مساعدة سمعية.
لو عندك مراجع صوت أصلية للتقييم، ابعت فرق SI-SDR لكل هدف بين المسارين؛
بوابة الفرز لا تسمح بتراجع أكبر من 0.5 dB. من غير مراجع وقياس، ما نعلنش اجتياز الجودة رقميًا.
المراجعة والقرار في [تقرير البوابة](06_REALTIME_GATE_REPORT.md) ومهمة القياس الموجودة؛
التسليم ده **مش** اجتياز للبوابة ومش اختبار Windows فعلي.

دي حدود المسار شبه المباشر الحالي. هدف خطة البث المستمر الأشد هو RTF ≤0.5
وp95 ≤1.5 ث، وصفر مقاطع مفقودة/مكررة، وفرق SI-SDRi عن الرفع ≤2 dB.
اجتياز حدود المسار القديم مش إثبات لتحقيق هدف البث المستمر.
قبل استخدام تقارير أداة تقييم العزل القديمة للاعتماد، أعد توليدها:
الفحص الحالي بيطلب كل الأهداف الجاهزة، ويرفض السكوت المكتشف بدقة 20 ms
أثناء كلام الهدف، بما فيه آخر إطار جزئي. خط أساس ناقص يدي نتيجة غير حاسمة؛
ناتج جديد ناقص مع خط أساس كامل يُرفض.

## الإيقاف والرجوع

Stop من الصفحة الأول، انتظر النتيجة أو رسالة الفشل، واقفل التبويب؛ بعدين Ctrl+C للعامل،
ثم API والواجهة. متقتلش API وهي لسه بتعالج لو تقدر تنتظر.
لو الجهاز اتقفل فجأة، راجع الملفات المؤقتة `focus-inference-*` في Windows TEMP
من غير لمس الكاش أو النسخة القديمة. للرجوع للرفع بس شغّل API من غير `-Live`
والواجهة بـ`VITE_LIVE_ENABLED=0`. حذف بيانات التجربة اختياري **بعد** إيقاف الكل؛
ما تمسحش أي ملفات من `A:\focus`.


تجربة WeSep البحثية على الموقع (اختيارية): [WESEP_WEBSITE_TRIAL.md](WESEP_WEBSITE_TRIAL.md).
