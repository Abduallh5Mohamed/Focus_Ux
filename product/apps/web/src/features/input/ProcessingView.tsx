import { Link } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Card, CardHead } from '../../components/Card';
import { Notice } from '../../components/Notice';
import { Pill, type PillTone } from '../../components/Pill';
import { ProgressBar } from '../../components/ProgressBar';
import { Spinner } from '../../components/Spinner';
import { describeError, isApiError } from '../../lib/api/errors';
import {
  JOB_STAGE_LABEL,
  JOB_STATUS_LABEL,
  isTerminalStatus,
  type JobStage,
  type JobState,
  type JobStatus,
  type TranscriptStatus,
} from '../../lib/api/types';
import './input.css';

export interface ProcessingViewProps {
  job: JobState | null;
  error: unknown;
  loading: boolean;
  polling: boolean;
  onRetry: () => void;
  onOpenResult: () => void;
}

/** Contract order of the pipeline. The rail is derived from the real `stage`, never guessed. */
const STAGE_ORDER: readonly JobStage[] = [
  'validating',
  'preparing',
  'tracking',
  'separating',
  'transcribing',
  'ready',
];

const STATUS_TONE: Record<JobStatus, PillTone> = {
  queued: 'neutral',
  processing: 'info',
  completed: 'ok',
  failed: 'danger',
  cancelled: 'neutral',
};

const TRANSCRIPT_LABEL: Record<TranscriptStatus, string> = {
  pending: 'في الانتظار',
  processing: 'بيتفرّغ دلوقتي',
  ready: 'جاهز',
  failed: 'فشل',
};

const TRANSCRIPT_TONE: Record<TranscriptStatus, PillTone> = {
  pending: 'neutral',
  processing: 'info',
  ready: 'ok',
  failed: 'warn',
};

/**
 * Live view of one job.
 *
 * There is deliberately no percentage and no ETA: the API only exposes status and stage,
 * so the bar stays indeterminate until a real fraction exists.
 */
export function ProcessingView(props: ProcessingViewProps): JSX.Element {
  const { job, error, loading, polling, onRetry, onOpenResult } = props;

  if (!job && loading) {
    return (
      <Card>
        <CardHead title="بنجيب حالة الطلب" hint="لسه مستنيين أول رد من الخادم." />
        <div className="row">
          <Spinner />
          <p className="card__hint">بنتأكد من حالة الطلب على الخادم…</p>
        </div>
      </Card>
    );
  }

  if (!job) {
    const failure = error ? describeError(error) : null;
    const fatal = isApiError(error) && !error.retryable;

    return (
      <Card>
        <CardHead title="حالة الطلب" hint="مش قادرين نجيب آخر حالة من الخادم." />
        <div className="stack">
          {failure ? (
            <Notice
              tone={fatal ? 'danger' : 'warn'}
              title={failure.title}
              code={failure.code}
              action={
                <Button size="sm" variant="secondary" icon="restart" onClick={onRetry}>
                  جرّب تاني
                </Button>
              }
            >
              {polling
                ? 'بنحاول نعيد الاتصال بالخادم تلقائيًا. لو الاستنى طال، جرّب يدويًا.'
                : failure.detail}
            </Notice>
          ) : (
            <Notice
              tone="info"
              title="لسه مفيش بيانات عن الطلب"
              action={
                <Button size="sm" variant="secondary" icon="restart" onClick={onRetry}>
                  جرّب تاني
                </Button>
              }
            >
              اطلب الحالة يدويًا عشان نعرف إحنا فين.
            </Notice>
          )}
        </div>
      </Card>
    );
  }

  const terminal = isTerminalStatus(job.status);
  const failure = error ? describeError(error) : null;
  const retryAction = (
    <Button size="sm" variant="secondary" icon="restart" onClick={onRetry}>
      جرّب تاني
    </Button>
  );

  return (
    <Card>
      <CardHead
        title="حالة المعالجة"
        hint={`المرحلة الحالية: ${JOB_STAGE_LABEL[job.stage]}`}
        action={
          <Pill tone={STATUS_TONE[job.status]} busy={job.status === 'processing'}>
            {JOB_STATUS_LABEL[job.status]}
          </Pill>
        }
      />

      <div className="stack">
        <p className="visually-hidden" aria-live="polite">
          {`${JOB_STATUS_LABEL[job.status]} — ${JOB_STAGE_LABEL[job.stage]}`}
        </p>

        {!terminal ? (
          <div className="stack stack--tight">
            <ProgressBar label="تقدّم المعالجة" />
            <p className="hint">
              المعالجة بتتم على الخادم، ومفيش نسبة دقيقة أو وقت متوقع نقدر نعرضهم من غير تخمين.
            </p>
          </div>
        ) : null}

        {job.status === 'queued' && job.queue_position > 0 ? (
          <Notice tone="info" title={`مستنيين دورك — فيه ${job.queue_position} طلب قبلك`}>
            هتبدأ المعالجة أول ما دورك يوصل.
          </Notice>
        ) : null}

        <StageRail stage={job.stage} status={job.status} />

        {failure && polling ? (
          <Notice tone="warn" title={failure.title} code={failure.code} action={retryAction}>
            بنحاول نعيد الاتصال بالخادم تلقائيًا.
          </Notice>
        ) : null}

        {!polling && !terminal ? (
          <Notice
            tone="warn"
            title="الحالة مش بتتحدث تلقائيًا دلوقتي"
            code={failure?.code}
            action={retryAction}
          >
            {failure
              ? `${failure.title} التحديث التلقائي واقف — جرّب تاني عشان تجيب آخر حالة.`
              : 'التحديث التلقائي وقف — جرّب تاني عشان تجيب آخر حالة من الخادم.'}
          </Notice>
        ) : null}

        {job.status === 'failed' ? (
          <Notice
            tone="danger"
            title="المعالجة وقفت"
            code={job.error?.code ?? undefined}
            action={<Link to="/upload">ارفع فيديو تاني</Link>}
          >
            <p>{job.error?.message ?? 'الخادم مبيّنش سبب واضح للفشل.'}</p>
            <p className="hint">
              {job.error
                ? job.error.retryable
                  ? 'الخطأ ده قابل لإعادة المحاولة، بس نفس الطلب مش هينفع يتكمل — ابدأ بفيديو تاني.'
                  : 'الخطأ ده مش قابل لإعادة المحاولة بنفس الفيديو.'
                : 'مفيش تفاصيل إضافية عن سبب الفشل.'}
            </p>
          </Notice>
        ) : null}

        {job.status === 'cancelled' ? (
          <Notice tone="info" title="الطلب اتلغى" action={<Link to="/upload">ارفع فيديو تاني</Link>}>
            مفيش نتيجة للطلب ده.
          </Notice>
        ) : null}

        {job.audio_status === 'failed' ? (
          <Notice tone="danger" title="الصوت المعزول مش جاهز">
            عزل الصوت فشل. ابدأ بفيديو تاني أو جرّب نفس الفيديو بعد شوية.
          </Notice>
        ) : null}

        {job.audio_status === 'ready' ? (
          <div className="stack stack--tight">
            <div>
              <Button variant="primary" icon="wave" iconEnd="arrow-left" onClick={onOpenResult}>
                افتح النتيجة
              </Button>
            </div>
            <p className="hint">
              الصوت المعزول جاهز. تفريغ النص مالوش علاقة بجاهزية الصوت، فتقدر تسمع وتنزّل دلوقتي.
            </p>
          </div>
        ) : null}

        <div className="row row--between">
          <span className="label">تفريغ النص</span>
          <Pill tone={TRANSCRIPT_TONE[job.transcript_status]} busy={job.transcript_status === 'processing'}>
            {TRANSCRIPT_LABEL[job.transcript_status]}
          </Pill>
        </div>

        {job.transcript_status === 'failed' ? (
          <p className="hint">تفريغ النص فشل، لكن الصوت المعزول مش متأثر بده.</p>
        ) : null}
      </div>
    </Card>
  );
}

function StageRail({ stage, status }: { stage: JobStage; status: JobStatus }) {
  const current = STAGE_ORDER.indexOf(stage);

  return (
    <ol className="stage-rail" aria-label="مراحل المعالجة">
      {STAGE_ORDER.map((item, index) => {
        // A stage only counts as passed when the server actually moved past it.
        const done = index < current || (status === 'completed' && index === current);
        const state = done
          ? 'done'
          : index === current
            ? status === 'failed'
              ? 'stopped'
              : 'current'
            : 'todo';

        return (
          <li
            key={item}
            className="stage-rail__item"
            data-state={state}
            aria-current={state === 'current' || state === 'stopped' ? 'step' : undefined}
          >
            <span className="stage-rail__dot" aria-hidden="true">
              {state === 'done' ? '✓' : index + 1}
            </span>
            {JOB_STAGE_LABEL[item]}
          </li>
        );
      })}
    </ol>
  );
}
