import { PageHeader } from '../components/PageHeader';
import { LiveFlow } from '../features/live';

export function LivePage() {
  return (
    <>
      <PageHeader
        eyebrow="تجريبي"
        title="سجّل واسمع بتأخير معلن"
        lead="سجّل من الكاميرا، اختار الشخص، واسمع صوته المعزول بعد ثواني. النص بيتعمل بعد ما توقف."
      />
      <LiveFlow />
    </>
  );
}
