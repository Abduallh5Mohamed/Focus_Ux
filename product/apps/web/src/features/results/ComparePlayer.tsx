import { Card, CardHead } from '../../components/Card';
import { Icon } from '../../components/Icon';
import { Notice } from '../../components/Notice';
import { Button } from '../../components/Button';
import { Spinner } from '../../components/Spinner';
import { describeError } from '../../lib/api/errors';
import { formatClock, formatDuration } from '../../lib/format';
import type { AudioTransport } from './useAudioTransport';
import './results.css';

export type TrackMode = 'original' | 'isolated';

interface ComparePlayerProps {
  transport: AudioTransport;
  mode: TrackMode;
  onModeChange: (mode: TrackMode) => void;
  originalAvailable: boolean;
  originalSource: 'memory' | 'fetched' | null;
  originalLoading: boolean;
  originalError: unknown;
  onRetryOriginal: () => void;
  isolatedReady: boolean;
  isolatedLoading: boolean;
  isolatedError: unknown;
  onRetryIsolated: () => void;
  durationMs?: number;
  sampleRate?: number;
}

/** Static bar pattern: a level display, not a computed waveform (we never fake analysis). */
const BARS = Array.from({ length: 56 }, (_, index) => {
  const wave = Math.sin(index * 0.7) * 0.35 + Math.sin(index * 0.23 + 1.4) * 0.3;
  return 0.28 + Math.abs(wave) * 0.72;
});

export function ComparePlayer({
  transport,
  mode,
  onModeChange,
  originalAvailable,
  originalSource,
  originalLoading,
  originalError,
  onRetryOriginal,
  isolatedReady,
  isolatedLoading,
  isolatedError,
  onRetryIsolated,
  durationMs,
  sampleRate,
}: ComparePlayerProps) {
  const total = transport.duration || (durationMs ? durationMs / 1000 : 0);
  const progress = total > 0 ? Math.min(1, transport.currentTime / total) : 0;
  const failure = isolatedError ? describeError(isolatedError) : null;

  return (
    <Card>
      <CardHead
        title="قارن الأصل بالمعزول"
        hint="نفس اللحظة في الاتنين — التبديل بيحافظ على موضع التشغيل."
        action={<span className="pill pill--neutral">{mode === 'isolated' ? 'المعزول' : 'الأصل'}</span>}
      />

      <div className="stack">
        <div className="segmented" role="radiogroup" aria-label="اختار المسار اللي تسمعه">
          <button
            type="button"
            role="radio"
            aria-checked={mode === 'original'}
            className="segmented__btn"
            disabled={!originalAvailable}
            onClick={() => onModeChange('original')}
          >
            الأصل
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={mode === 'isolated'}
            className="segmented__btn"
            disabled={!isolatedReady}
            onClick={() => onModeChange('isolated')}
          >
            المعزول
          </button>
        </div>

        {originalLoading ? (
          <div className="row" aria-live="polite">
            <Spinner />
            <span className="hint">بنحمّل الصوت الأصلي من الخادم…</span>
          </div>
        ) : null}

        {originalError ? (
          <Notice
            tone="warn"
            title="مقادرناش نجيب الصوت الأصلي"
            action={
              <Button size="sm" variant="secondary" icon="restart" onClick={onRetryOriginal}>
                جرّب تاني
              </Button>
            }
          >
            لسه تقدر تسمع وتنزّل الصوت المعزول. الصوت الأصلي ممكن يكون اتحذف أو الرابط قديم.
          </Notice>
        ) : null}

        {!originalAvailable && !originalLoading && !originalError ? (
          <p className="hint">
            {originalSource === 'fetched'
              ? 'الصوت الأصلي اتحمّل من الخادم عشان نقارن بيه بعد إعادة التحميل.'
              : 'الصوت الأصلي متاح بس في نفس الجلسة اللي رفعت فيها الفيديو. بعد إعادة تحميل الصفحة من غير ما يكون محفوظ، المعزول بس المتاح — ومش بنعيد بناء الأصل من التخزين.'}
          </p>
        ) : null}

        {originalAvailable ? (
          <p className="hint">
            {originalSource === 'memory'
              ? 'الصوت الأصلي من نفس الفيديو اللي رفعته في الجلسة دي.'
              : 'الصوت الأصلي اتجاب من الخادم (نفس المدخل اللي اتعزل منه الصوت).'}
          </p>
        ) : null}

        <div className="player">
          <audio ref={transport.audioRef} preload="metadata" aria-label="مشغل المقارنة" />

          <div className="player__level" aria-hidden="true">
            {BARS.map((height, index) => (
              <span
                key={index}
                className="player__bar"
                data-passed={index / BARS.length <= progress}
                style={{ height: `${Math.round(height * 100)}%` }}
              />
            ))}
          </div>

          <div className="transport">
            <button
              type="button"
              className="transport__play"
              onClick={transport.toggle}
              disabled={!isolatedReady && !originalAvailable}
              aria-label={transport.playing ? 'إيقاف مؤقت' : 'تشغيل'}
            >
              {transport.buffering ? (
                <Spinner />
              ) : (
                <Icon name={transport.playing ? 'pause' : 'play'} size={22} />
              )}
            </button>

            <div className="transport__seek">
              <input
                className="seek"
                type="range"
                min={0}
                max={total > 0 ? total : 1}
                step={0.1}
                value={Math.min(transport.currentTime, total > 0 ? total : 0)}
                onChange={(event) => transport.seek(Number(event.target.value))}
                disabled={total <= 0}
                aria-label="موضع التشغيل"
                aria-valuetext={`${formatClock(transport.currentTime)} من ${formatClock(total)}`}
              />
              <div className="transport__times mono">
                <span>{formatClock(transport.currentTime)}</span>
                <span>{formatClock(total)}</span>
              </div>
            </div>
          </div>
        </div>

        {isolatedLoading ? (
          <div className="row" aria-live="polite">
            <Spinner />
            <span className="hint">بنحمّل الصوت المعزول…</span>
          </div>
        ) : null}

        {failure ? (
          <Notice
            tone="danger"
            title={failure.title}
            code={failure.code}
            action={
              <Button size="sm" icon="restart" onClick={onRetryIsolated}>
                جرّب تحميل الصوت تاني
              </Button>
            }
          >
            {failure.detail}
          </Notice>
        ) : null}

        <div className="row row--between">
          <p className="hint">
            المسارين مش متساويين في مستوى الصوت. الأصل الأعلى مش معناه عزل أسوأ — العزل بيتقاس
            بجودة الكلام مش بالعلو.
          </p>
          <p className="hint mono">
            {formatDuration(durationMs)}
            {sampleRate ? ` · ${sampleRate.toLocaleString('en-US')} Hz` : ''}
          </p>
        </div>
      </div>
    </Card>
  );
}
