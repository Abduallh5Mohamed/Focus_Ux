import { useNavigate, useParams } from 'react-router-dom';

import { Button } from '../components/Button';
import { Card } from '../components/Card';
import { PageHeader } from '../components/PageHeader';
import { Spinner } from '../components/Spinner';
import { Steps } from '../components/Steps';
import { ResultView } from '../features/results';
import { isApiError } from '../lib/api/errors';
import { clearJob, readSession } from '../lib/session';
import { useJob } from '../lib/useJob';

export function ResultPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const { job, error, loading, polling, refresh } = useJob(jobId ?? null);

  if (!jobId) return <p>الرابط ناقص.</p>;

  if (!job) {
    if (loading || polling) {
      return (
        <Card>
          <div className="row">
            <Spinner />
            <span>بنحمّل حالة الطلب…</span>
          </div>
        </Card>
      );
    }

    const unauthorized = isApiError(error) && error.isAuthFailure;
    return (
      <Card>
        <div className="stack">
          <h2 className="card__title">
            {unauthorized ? 'انتهت الجلسة' : 'مش لاقيين الطلب'}
          </h2>
          <p className="card__hint">
            {unauthorized
              ? 'مش مسموح نفتح الطلب ده من المتصفح الحالي.'
              : 'ممكن الطلب اتحذف أو الرابط قديم.'}
          </p>
          <div className="row">
            <Button variant="primary" onClick={() => navigate('/upload')}>
              ارفع فيديو جديد
            </Button>
            {!unauthorized ? (
              <Button variant="ghost" onClick={refresh}>
                جرّب تاني
              </Button>
            ) : null}
          </div>
        </div>
      </Card>
    );
  }

  return (
    <>
      <Steps current={4} />
      <PageHeader
        eyebrow="الخطوة 4"
        title="النتيجة"
        lead="بدّل بين الأصل والمعزول على نفس اللحظة، واسمع الفرق بنفسك قبل التنزيل."
      />
      <ResultView
        job={job}
        videoId={readSession().videoId}
        onDeleted={() => {
          clearJob();
          navigate('/', { replace: true });
        }}
      />
    </>
  );
}
