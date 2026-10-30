import { PageHeader } from '../components/PageHeader';
import { LiveFlow, LiveStreamFlow } from '../features/live';
import { LIVE_STREAM } from '../lib/env';

export function LivePage() {
  return (
    <>
      <PageHeader
        eyebrow="تجريبي"
        title="سجّل واسمع بتأخير معلن"
        lead="سجّل من الكاميرا، اختار الشخص، واسمع صوته المعزول بعد ثواني. النص بيتعمل بعد ما توقف."
      />
      {LIVE_STREAM ? <LiveStreamFlow /> : <LiveFlow />}
    </>
  );
}
