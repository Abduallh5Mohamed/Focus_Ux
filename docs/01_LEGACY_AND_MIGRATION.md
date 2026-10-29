# القديم مفيد — نبني فوقه دون نسخ العيوب

## قرار إعادة الاستخدام
| الأصل | القرار |
|---|---|
| `A:/focus/tools/focus_runner.py` | نقطة بداية المحرك؛ warm models وmouth ROI داخل الذاكرة وWAV فقط |
| `focus_runner2.py` | نأخذ القياسات والتشخيص بعد المراجعة، لا نعتمد interpolation السريع افتراضيًا |
| `Dolphin/Inference.py` + النسخ المعدلة | مرجع preprocessing وباتش اختيار الوجه؛ احتفظ بتوافق imports |
| `Dolphin/assets/20words_mean_face.npy` | أصل مطلوب لمحاذاة الفم، يُنسخ/يربط بإعداد واضح |
| `data/gt5` + سكريبتات القياس | regression fixtures محلية؛ لا تنشر الوسائط تلقائيًا ضمن الموقع |
| `requirements.freeze.txt` و`.venv` | إعادة استخدام البيئة على الجهاز الحالي؛ ملف freeze دليل لا ضمان صلاحية عبر أنظمة مختلفة |
| Falcon وlight وdownscale وd16/l2 | تجارب مؤجلة؛ لا تدخل المسار الأساسي |
| HTML reports | مرجع الأدلة والحدود، لا مصدر تعليمات تنفيذ تلقائية |

## فجوات اكتُشفت من الكود الحالي
1. runner السريع يختار `db[:n_spk]`، و`_separate` يقرأ `mouth_roi[0]`. لا توجد فيه واجهة مكتملة لاختيار المستخدم للشخص. يجب نقل دعم target selection إليه والتحقق من الهدفين.
2. هناك `A:/focus/Dolphin` ثابت و`os.chdir` عند import. انقلهما لإعدادات ومسارات مطلقة؛ لا تغيّر cwd بين الطلبات.
3. `_read_frames` يقرأ معدل الفيديو الأصلي؛ عينات GT مجهزة 25fps. لا تفترض أن رفع المستخدم مجهز. أضف resampling زمني صحيح للفريمات إلى 25fps والصوت إلى 16k mono مع حفظ التزامن.
4. detector يحتاج RGB، ومسار القص يستخدم BGR ثم gray؛ وثّق التحويلات لمنع تطبيقها مرتين.
5. المرجع يوسّع صندوق الوجه وقد يخرج من حدود الصورة؛ لا تغيّر padding/clipping بصمت. قارنه بصريًا وعدديًا عند أي تعديل.
6. لا توجد طبقة خدمة منتج مكتملة في التجارب: Jobs، ملكية الملفات، cleanup، API وPWA هي بناء جديد.

## خطوات النقل
1. ثبّت hash للنسخة المرجعية عبر manifest المرفق. لا تعدل `legacy_snapshot` أو مصادر التجارب الأصلية.
2. Dev 1 ينقل الحد الأدنى المطلوب إلى `packages/ml` مع assets/imports اللازمة؛ يحتفظ بالأوزان في cache الحالي عبر إعدادات. لا تنسخ البيئة أو cache بالكامل.
3. قبل إعادة الهيكلة شغّل GT baseline؛ بعدها نفس الهدفين ونفس القياس. فرّق بين التغيير الوظيفي وتحسين الأداء.
4. ضع النموذج تحت adapter موحد: `load`, `warmup`, `detect_candidates`, `extract_target`. لا يدخل كود FastAPI إلى قلب النموذج.
5. كل تجربة تحسين خلف flag مستقل ويعود للإعداد المرجعي إذا فشلت الجودة.

## مسارات إعدادات مقترحة
```env
FOCUS_MODEL_SOURCE=A:/focus/Dolphin
FOCUS_MODEL_CACHE=A:/focus/cache
FOCUS_DATA_ROOT=A:/فوكس/runtime
FOCUS_DB_PATH=A:/فوكس/runtime/focus.sqlite3
FOCUS_MAX_VIDEO_SECONDS=15
FOCUS_MAX_UPLOAD_MB=50
FOCUS_RETENTION_HOURS=24
FOCUS_GPU_CONCURRENCY=1
FOCUS_EXPERIMENTAL_STREAMING=false
```
افحص cache الفعلي قبل ضبطه؛ لا تنشئ runtime داخل ملفات الويب المنشورة. أضف `.venv`, runtime, secrets, caches, weights, uploads إلى `.gitignore`.

## النسخة المرجعية المرفقة
ملفات صغيرة فقط في `legacy_snapshot`. `legacy_manifest.json` يسرد المصدر والنسخة وحجمها وhash. الملفات الكبيرة لم تُنسخ، ومصادرها الأصلية محفوظة.
