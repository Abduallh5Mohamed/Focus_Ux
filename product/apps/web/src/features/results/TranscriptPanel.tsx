import { useMemo } from 'react';

import { Button } from '../../components/Button';
import { Card, CardHead } from '../../components/Card';
import { EmptyState } from '../../components/EmptyState';
import { Notice } from '../../components/Notice';
import { Pill } from '../../components/Pill';
import { ProgressBar } from '../../components/ProgressBar';
import { describeError } from '../../lib/api/errors';
import type { TranscriptResponse, TranscriptStatus } from '../../lib/api/types';
import { formatTimestamp } from '../../lib/format';
import './results.css';

interface TranscriptPanelProps {
  status: TranscriptStatus;
  transcript: TranscriptResponse | null;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  currentTime: number;
  onSeek: (seconds: number) => void;
  onDownload: () => void;
}

export function TranscriptPanel({
  status,
  transcript,
  loading,
  error,
  onRetry,
  currentTime,
  onSeek,
  onDownload,
}: TranscriptPanelProps) {
  const segments = transcript?.segments ?? [];

  const activeIndex = useMemo(() => {
    const ms = currentTime * 1000;
    return segments.findIndex((segment) => ms >= segment.start_ms && ms < segment.end_ms);
  }, [segments, currentTime]);

  const failure = error ?? transcript?.error ?? null;

  return (
    <Card>
      <CardHead
        title="النص"
        hint="نص آلي غير مُراجع بشريًا — للاسترشاد فقط."
        action={
          <Button
            size="sm"
            variant="ghost"
            icon="download"
            onClick={onDownload}
            disabled={status !== 'ready' || segments.length === 0}
          >
            تنزيل النص
          </Button>
        }
      />

      {status === 'pending' || status === 'processing' || loading ? (
        <div className="stack stack--tight" aria-live="polite">
          <div className="row">
            <Pill tone="info" busy>
              {status === 'processing' ? 'بيتفّرغ' : 'في الانتظار'}
            </Pill>
          </div>
          <ProgressBar label="حالة التفريغ النصي" />
          <p className="hint">
            النص بيتجهز بعد الصوت. تقدر تسمع وتنزّل المعزول من غير ما تستنى.
          </p>
        </div>
      ) : null}

      {status === 'failed' ? (
        <div className="stack stack--tight">
          <Notice
            tone="warn"
            title="التفريغ النصي فشل"
            code={failure ? describeError(failure).code : undefined}
            action={
              <Button size="sm" variant="secondary" icon="restart" onClick={onRetry}>
                جرّب تاني
              </Button>
            }
          >
            الصوت المعزول شغال عادي. المشكلة في النص بس.
          </Notice>
        </div>
      ) : null}

      {status === 'ready' && segments.length === 0 ? (
        <EmptyState icon="file" title="مفيش كلام اتعرّف عليه">
          يمكن المقطع مفيهوش كلام واضح، أو الصوت منخفض جدًا.
        </EmptyState>
      ) : null}

      {status === 'ready' && segments.length > 0 ? (
        <ol className="transcript">
          {segments.map((segment, index) => (
            <li key={segment.id}>
              <button
                type="button"
                className="transcript__row"
                data-active={index === activeIndex}
                onClick={() => onSeek(segment.start_ms / 1000)}
              >
                <span className="transcript__time mono">{formatTimestamp(segment.start_ms)}</span>
                <span className="transcript__text">{segment.text}</span>
              </button>
            </li>
          ))}
        </ol>
      ) : null}

      {status === 'ready' && segments.length > 0 ? (
        <p className="hint" style={{ marginTop: 'var(--sp-3)' }}>
          دوس على أي جملة تروح لنفس اللحظة في المسار اللي مختاره.
        </p>
      ) : null}
    </Card>
  );
}
