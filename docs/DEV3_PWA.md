# Dev 3 — PWA وUpload واختيار الوجه

## ملكيتك
web scaffold والتوجيه وPWA shell وصفحات البداية/upload/select/process، typed API client. تنسق مع Dev 4 ملفات routes/lockfile المشتركة.

## اليوم الأول
- [ ] H0–1: Vite React TypeScript، layout RTL، routes ومكونات أولية مع UI/UX، fixtures مشتركة.
- [ ] H1–3: رفع مع progress ومعاينة وحدود قبل الإرسال؛ خادم يتحقق أيضًا. unsupported/no audio/oversize حالات قابلة للتصرف.
- [ ] H3–6: ربط Upload/face candidates/start job؛ اختيار واضح ثم تأكيد، selected_face_id لا index محلي.
- [ ] H6–9: polling مع backoff بسيط عند خطأ الشبكة، مراحل queue/prepare/track/separate؛ لا نسبة أو ETA مخترعين.
- [ ] H6–9: حفظ job ID ورمز session محليًا دون تضمينه URL، استرجاع الطلب بعد refresh، التعامل مع حذف/انتهاء الطلب.
- [ ] H9–12: manifest وأيقونات وstandalone، HTTPS، offline shell ورسالة واضحة، اختبار mobile/desktop.

## PWA بدقة
Cache للواجهة الثابتة فقط. استبعد API وuploads والنتائج الخاصة من caching. لا تدّعِ GPU offline. لا تعِد رفع job عند عودة الشبكة دون تحقق من client_request_id. تجربة التثبيت حسب دعم المتصفح، ولا تعطل المستخدم بطلب تثبيت عند الدخول.

## اليوم الثاني — تسجيل تجريبي
كاميرا/ميك بإذن المستخدم، preview واختيار target/start/stop. تحقق MIME المدعوم. أوقف tracks عند stop/unmount. لا تفترض WebM موحدًا لكل الأجهزة. واجهة التجربة خلف feature flag، وتحفظ upload كمسار أساسي.

حالات: permission denied، camera unavailable، disconnect، target lost، backlog، stopping. سماعات لتجربة playback أثناء capture. لو لم تجتز بوابة realtime، استخدم تسجيل قصير ثم رفع مع تسمية صادقة.

## تسليمك
routes وtyped client ومراحل واضحة، PWA قابلة للتثبيت حيث مدعومة، استرجاع طلب. نسق result route مع Dev 4 منذ H1؛ لا تنتظر backend لبناء الحالات على fixtures.
