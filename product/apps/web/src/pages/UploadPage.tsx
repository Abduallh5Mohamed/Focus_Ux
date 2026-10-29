import { useNavigate } from 'react-router-dom';

import { PageHeader } from '../components/PageHeader';
import { Steps } from '../components/Steps';
import { IntakeFlow } from '../features/input';
import { saveSession } from '../lib/session';

export function UploadPage() {
  const navigate = useNavigate();

  return (
    <>
      <Steps current={1} />
      <PageHeader
        eyebrow="الخطوة 1"
        title="ارفع الفيديو"
        lead="اختار مقطع قصير فيه المتكلم ظاهر والوش واضح. التحقق النهائي من الصيغة والمدة بيحصل على الخادم."
      />
      <IntakeFlow
        onUploaded={(videoId) => {
          saveSession({ videoId, jobId: null });
          navigate(`/select/${videoId}`);
        }}
      />
    </>
  );
}
