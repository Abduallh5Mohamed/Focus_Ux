# النشر المجاني المقترح للمسابقة

## البنية
PWA static على Cloudflare Pages → HTTPS API عبر Cloudflare Tunnel → FastAPI + SQLite + worker على جهاز RTX 3060.

هذا نشر يعتمد على جهاز الفريق وإنترنت الجهاز؛ ليس GPU سحابي مستقلًا أو ضمان توفر. GPU واحد وqueue محدودة، والنشر لا يزيل بطء preprocessing.

## خطوات Dev 2 وDev 3
1. شغّل API/worker محليًا أولًا، واربط frontend باستخدام API_BASE_URL قابل للتغيير.
2. انشر static build للواجهة على Pages. إذا المشروع Next.js استخدم static export أو خط نشر مناسب بدل افتراض دعم SSR.
3. استخدم Tunnel إلى منفذ API المحدد. Quick Tunnel للتجربة؛ hostname يتغير عند إعادة التشغيل، فلا تدفنه في source code.
4. إن توفر domain يمكن إعداد tunnel باسم ثابت؛ لا تشترِ أو تغير DNS دون تفويض. البديل تحديث API URL وإعادة build قبل العرض.
5. اضبط CORS على أصل الواجهة فقط، وHTTPS وحماية session token.
6. POST/202 + polling، لا اتصال ينتظر inference بالكامل. رفع الوسائط مباشرة للـAPI؛ حدود الخادم 50MB/15s كبداية.
7. اختبر من بيانات الهاتف، لا من شبكة الجهاز فقط. الجهاز على الشاحن وSleep معطل أثناء العرض بإعداد متفق عليه.

## فحوص العرض
- health يعكس worker/model readiness، لا مجرد API alive.
- warmup قبل العرض، queue فارغة، مساحة كافية، sample احتياطي.
- اختبر restart واستعادة الطلب، والتأكد من URL الصحيح.
- سجل مدة الانتظار ولا تَعِد بتزامن عدة عمليات عزل على 6GB.

## المصادر التي بُني عليها القرار
- https://developers.cloudflare.com/pages/platform/limits/
- https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/

راجِع الحدود وقت التنفيذ. Quick Tunnel بلا ضمان uptime ولا SSE. Free hosting للواجهة لا يساوي قدرة GPU مجانية. ZeroGPU بديل تجريبي مشروط بالأهلية والتوافق، وليس اعتماد تسليم اليوم الأول.
