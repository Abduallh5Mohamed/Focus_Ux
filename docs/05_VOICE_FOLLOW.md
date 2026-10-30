# متابعة الشخص بصوته لما الوش يختفي

## الحالة
منطق البصمة والتبديل والثقة والقياس منفّذ في `focus_ml/voice_follow.py` مع اختبارات.
**نموذج البصمة ونموذج العزل بالبصمة غير مدمجين، ولا تنزيل قبل موافقة الفريق.** المُدمِج يُحقن عبر `SpeakerEmbedder`.

## قواعد
- التسجيل: من فترات الوش ظاهر + الشفايف بتتحرك + جودة كافية، أقل مدة 4 ثواني (قابلة للضبط 3–5). قبلها لا توجد بصمة.
- الوش مخفي: تشابه >= العتبة → `voice_follow`؛ أقل → `uncertain` والصوت مكتوم (مش صوت شخص تاني).
- الوش ظاهر والتشابه < عتبة التعارض → `conflict` مسجّل والصوت مكتوم.
- البصمة في الذاكرة لجلسة الطلب فقط وتتمسح (`discard()`).
- الفترات: `{start_ms,end_ms,state,reason,similarity,output_allowed}` في `result.follow_periods` (اختياري).

## خيارات النماذج (للموافقة، لا تنزيل حاليًا)
| الغرض | خيار | ملاحظات |
|---|---|---|
| بصمة صوتية | SpeechBrain ECAPA-TDNN (spkrec-ecapa-voxceleb) | Apache-2.0، ~80MB، سريع على CPU، EER ~1% على VoxCeleb |
| بصمة صوتية | WeSpeaker ResNet34 | Apache-2.0، ~25MB، أخف |
| عزل بالبصمة | SpeakerBeam / VoiceFilter-style | تراخيص الأوزان المتاحة محتاجة مراجعة؛ ممكن تدريب داخلي (خارج النطاق) |
| بديل بدون عزل جديد | إعادة ترتيب مخرجات Dolphin بأقرب بصمة | لا يغطي غياب الشفايف كليًا |
راجع الترخيص والحجم والسرعة قبل اختيار أي منها.

## Audio-only voice pipeline (proof of concept)
See `docs/VOICE_PIPELINE.md` and `docs/VOICE_PIPELINE_LOG.md`. Windows: `product\tools\Setup-Voice.cmd` (approval first, own environment `%LOCALAPPDATA%\FocusVoice`), then `product\tools\Voice-Readiness.cmd`. The original Dolphin environment is not changed.
