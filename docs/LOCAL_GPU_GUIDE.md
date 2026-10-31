# تشغيل FOCUS محليًا على أي كارت NVIDIA بـ CUDA

دليل واحد للتشغيل والتحقق. مفيش افتراض لموديل كارت معين ولا أرقام أداء: كل الأرقام اللي
بتظهر في الأدوات تقديرات من حجم الموديل، مش قياسات.

## المتطلبات
- ويندوز، كارت NVIDIA، درايفر حديث (`nvidia-smi` شغال).
- Python فيه PyTorch بنسخة CUDA (مش CPU-only).
- مجلد الموديلات: `Dolphin\` و`cache\hf\` و`cache\torch\`.

## إعدادات (كلها اختيارية، متغيرات بيئة في نفس نافذة الأوامر)
| المتغير | معناه | الافتراضي |
|---|---|---|
| `FOCUS_PYTHON` | مسار `python.exe` اللي فيه CUDA PyTorch | أول `.venv-ml` / `.venv` / `venv` جوه المشروع فيه torch، ثم `python` من PATH |
| `FOCUS_HOME` | المجلد اللي فيه `Dolphin\` و`cache\` | مجلد المشروع |
| `FOCUS_MODEL_SOURCE` / `FOCUS_MODEL_CACHE` / `FOCUS_TORCH_HOME` | تحديد كل جزء لوحده | تحت `FOCUS_HOME` |
| `FOCUS_VOICE_HOME` | أوزان الصوت وWeSep وحزمها | `runtime\voice` |
| `FOCUS_OVERLAP_VRAM_BUDGET_MIB` / `FOCUS_OVERLAP_WINDOW_S` / `FOCUS_OVERLAP_BATCH_SIZE` | تثبيت حجم نافذة WeSep والدفعة يدويًا | تلقائي من الذاكرة الحرة |
| `FOCUS_MIN_VRAM_MIB` | أقل VRAM لفحص جاهزية الصوت | 3500 |
| `FOCUS_REQUIRED_DRIVE` | (`run_local.ps1`) لو عايز تلزم المشروع بدرايف معين، مثلًا `D:` | مفيش إلزام |

لو `FOCUS_PYTHON` متحدد ومش موجود، الأدوات بتقف برسالة واضحة ومش بتختار بيئة تانية بصمت.

## 1) افحص الجهاز (قراءة فقط)
```
product\tools\Focus-Check-GPU.cmd
```
بيطبع: الكارت والدرايفر وVRAM الحر وCUDA، الـ Python المستخدم، مجلدات الموديلات، وجود أوزان
الصوت وWeSep، وحجم نافذة/دفعة WeSep المقترح. بيكتب `gpu-check-out\gpu_check.json`. مابيحملش
موديل ومابينزلش حاجة ومابيقيسش سرعة. مع موقع بعيد: `Focus-Check-GPU.cmd --url https://...`.

## 2) سيناريو أ: الموقع والـ API على نفس الجهاز
1. `scripts\start-local-api.ps1` (الـ API) و`product\tools\run_local.ps1` (الواجهة والمحرك المحلي)
   حسب `docs\LOCAL_WINDOWS_TRIAL.md`.
2. `Setup-Key.cmd` ثم `Check-Connection.cmd --local-api` ثم `Start-Worker.cmd --local-api`.

## 3) سيناريو ب: موقع بعيد وعامل GPU محلي
1. نزّل حزمة العامل من الموقع واستخرجها في مجلد جديد.
2. `Setup-Key.cmd` (المفتاح للمخزن السري `FOCUS_WORKER_TOKEN` فقط).
3. `Check-Connection.cmd` ثم `Start-Worker.cmd`. العامل بيطبع الكارت واستعماله للذاكرة قبل تحميل الموديلات،
   ويقف برسالة لو مفيش GPU صالح.

## 4) ترتيب التحقق
1. `Focus-Check-GPU.cmd`
2. `Check-Connection.cmd` (لا يحمّل موديلات)
3. `Overlap-Validate.cmd enroll.wav mixture_5_10s.wav recording_with_overlap.wav` (فحص مسبق ثم استخراج حقيقي
   لخليط واحد ثم تجربة كاملة). بيوقف عند أول فشل.
4. `Start-Worker.cmd` وارفع مقطع قصير من الموقع.

## الضبط التلقائي حسب الـ VRAM
نافذة WeSep 4 ثم 3 ثم 2 ثانية، والدفعة من الذاكرة الحرة بعد هامش 1024 MiB. الأرقام لكل موديل
(`vram_base_mib` و`vram_per_window_s_mib`) تقديرات متحفظة. لو حصل out-of-memory وقت التشغيل، الدفعة
بتتقسم على اتنين تلقائيًا. منطق WeSep واسترجاع المتحدث الهادي ماتغيرش.

## اللي لسه محتاج جهازك الحقيقي (ماتجربش من Replit)
- الاستخراج الحقيقي بـ WeSep على خليط واحد (`Overlap-Validate.cmd` الخطوة 2).
- التجربة الكاملة end-to-end على تسجيل فيه تداخل (الخطوة 3).
- تشغيل العامل ضد موقع حقيقي (بعيد ومحلي).
- أي رقم سرعة أو VRAM أو جودة، ومعها `Profile-Speed.cmd` و`Final-Evaluation.cmd`.
- ملفات `.cmd` نفسها (اختيار Python والرسائل) اتكتبت لكن ماجربتش على ويندوز؛ الاختبارات الآلية
  بتتأكد بس إن مفيش مسار ثابت وإن كل ملف بيعدّي على `focus_env.cmd`.
