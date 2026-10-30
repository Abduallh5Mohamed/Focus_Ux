# نموذج موافقة على تسجيل الصوت — FOCUS
# Voice recording consent form — FOCUS

**الاسم / Name:** ______________________  **رمز المتحدث / Speaker ID (يملأه الفريق):** S____
**التاريخ / Date:** ____________  **رقم الموافقة / Consent ID:** C____

أوافق على تسجيل صوتي لغرض واحد فقط: **اختبار وتقييم نظام FOCUS** لفصل صوت شخص محدد وتمييز المتحدثين.
I agree to my voice being recorded for one purpose only: **testing and evaluating FOCUS**, which tells speakers apart and keeps one chosen voice.

1. **الاستخدام / Use:** التسجيلات تُستخدم للقياس الداخلي فقط. لا تدريب ولا ضبط نماذج، ولا مشاركة خارج الفريق. / Recordings are used for internal measurement only: no model training or fine-tuning, no sharing outside the team.
2. **بصمة الصوت / Voiceprint:** قد يُحسب من تسجيلي رقم يصف خصائص صوتي. يبقى على أجهزة الفريق ولا يُستخدم للتعرف عليّ خارج هذا الاختبار. / A number describing my voice may be computed from my recording. It stays on the team's devices and is not used to identify me outside this test.
3. **لا نصوص / No transcripts:** لا يُحوَّل كلامي إلى نص ولا يُحلَّل محتواه. / My speech is not transcribed and its content is not analysed.
4. **الحذف / Deletion:** يمكنني طلب حذف تسجيلاتي في أي وقت من: ______________________
5. **التطوع / Voluntary:** المشاركة اختيارية ويمكنني التوقف في أي لحظة. / Taking part is voluntary and I can stop at any time.
6. **الأشخاص الآخرون / Other people:** لا أسجّل أحدًا غيري إلا بموافقته المكتوبة. / I do not record anyone else without their written consent.

التوقيع / Signature: ______________________

بعد التوقيع يضيف الفريق في `manifest.json`: `{"id": "C..", "speaker_id": "S..", "signed": true, "date": "YYYY-MM-DD"}` — التسجيل بلا موافقة موقّعة يرفضه سكربت التحقق.
After signing, the team adds the entry above to `manifest.json`; the validation script rejects recordings without a signed consent.
