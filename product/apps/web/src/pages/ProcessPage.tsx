import { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { Button } from '../components/Button';
import { Card } from '../components/Card';
import { PageHeader } from '../components/PageHeader';
import { Steps } from '../components/Steps';
import { ProcessingView } from '../features/input';
import { isApiError } from '../lib/api/errors';
import { useJob } from '../lib/useJob';

export function ProcessPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const { job, error, loading, polling, refresh } = useJob(jobId ?? null);

  // The audio is usable before the transcript is; go to results as soon as it exists.
  useEffect(() => {
    if (job?.audio_status === 'ready') {
      navigate(`/job/${job.job_id}/result`, { replace: true });
    }
  }, [job, navigate]);

  if (!jobId) {
    return <p>الرابط ناقص.</p>;
  }

  const unauthorized = isApiError(error) && error.isAuthFailure;

  return (
    <>
      <Steps current={3} />
      <PageHeader
        eyebrow="الخطوة 3"
        title="جاري المعالجة"
        lead="المعالجة بتتم على الخادم. سيب الصفحة مفتوحة — الحالة بتتحدث تلقائيًا."
      />

      {unauthorized ? (
        <Card>
          <div className="stack">
            <h2 className="card__title">انتهت الجلسة</h2>
            <p className="card__hint">
              مش قادرين نوصل للطلب ده من المتصفح الحالي. ابدأ برفع الفيديو من جديد.
            </p>
            <div className="row">
              <Button variant="primary" onClick={() => navigate('/upload')}>
                ارفع فيديو جديد
              </Button>
            </div>
          </div>
        </Card>
      ) : (
        <ProcessingView
          job={job}
          error={error}
          loading={loading}
          polling={polling}
          onRetry={refresh}
          onOpenResult={() => navigate(`/job/${jobId}/result`)}
        />
      )}
    </>
  );
}
