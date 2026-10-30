import { useEffect, useRef, useState } from 'react';

import { Button } from '../../components/Button';
import { Card, CardHead } from '../../components/Card';
import { Notice } from '../../components/Notice';
import { Pill } from '../../components/Pill';
import { Spinner } from '../../components/Spinner';
import { useApi } from '../../lib/api/ApiContext';
import { describeError, isApiError } from '../../lib/api/errors';
import type {
  AnalysisResponse,
  EnrollmentState,
  SuggestionResponse,
  VoiceCandidateInfo,
} from '../../lib/api/types';
import { formatTimestamp } from '../../lib/format';
import './input.css';

/** Shortest clean speech the server accepts for a voiceprint (mirrors the server's refusal). */
export const MIN_ENROLL_MS = 4_000;
export const MAX_RANGE_MS = 60_000;
const POLL_MS = 1_500;
const MAX_POLLS = 120;

type Mode = 'voice' | 'range' | 'file';

export interface VoiceConfirmProps {
  videoId: string;
  faceId: string;
  onJobCreated: (jobId: string) => void;
  onBack?: () => void;
}

/**
 * Voice confirmation: the visitor listens to each detected voice and confirms which one is
 * the chosen person. The ranking is a suggestion from on-screen evidence; nothing is
 * accepted until the visitor confirms it, and the choice is the only thing sent on.
 */
export function VoiceConfirm({ videoId, faceId, onJobCreated, onBack }: VoiceConfirmProps): JSX.Element {
  const api = useApi();
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [suggestion, setSuggestion] = useState<SuggestionResponse | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);

  const [mode, setMode] = useState<Mode>('voice');
  const [voiceId, setVoiceId] = useState<string | null>(null);
  const [rangeStart, setRangeStart] = useState(0);
  const [rangeEnd, setRangeEnd] = useState(0);
  const [file, setFile] = useState<File | null>(null);

  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<unknown>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [enrollWarnings, setEnrollWarnings] = useState<string[]>([]);
  const requestId = useRef<string | null>(null);
  const preselected = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    let timer: number | undefined;
    let polls = 0;
    setLoadError(null);
    preselected.current = false;

    const tick = async () => {
      polls += 1;
      try {
        const [a, s] = await Promise.all([
          api.getAnalysis(videoId, controller.signal),
          api.getSuggestion(videoId, faceId, controller.signal).catch(() => null),
        ]);
        if (cancelled) return;
        setAnalysis(a);
        setSuggestion(s);
        setRangeEnd((end) => (end > 0 ? end : Math.min(a.duration_ms, 10_000)));
        const settled = a.status !== 'pending' && s !== null && s.status !== 'pending';
        if (!settled && polls < MAX_POLLS) timer = window.setTimeout(() => void tick(), POLL_MS);
      } catch (caught) {
        if (cancelled || (isApiError(caught) && caught.code === 'ABORTED')) return;
        setLoadError(caught);
      }
    };

    void (async () => {
      try {
        await api.requestSuggestion(videoId, faceId);
      } catch (caught) {
        if (!cancelled) setLoadError(caught);
        return;
      }
      if (!cancelled) void tick();
    })();

    return () => {
      cancelled = true;
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [api, videoId, faceId, attempt]);

  // Pre-select the suggested voice once, without confirming it.
  useEffect(() => {
    if (preselected.current || !analysis || !suggestion) return;
    const top = suggestion.candidates.find((c) => c.suggested);
    if (top) {
      setVoiceId(top.voice_id);
      preselected.current = true;
    }
  }, [analysis, suggestion]);

  const voices = analysis?.voices ?? [];
  const ordered = orderVoices(voices, suggestion);
  const suggestedId = suggestion?.candidates.find((c) => c.suggested)?.voice_id ?? null;
  const selected = voices.find((v) => v.voice_id === voiceId) ?? null;
  const durationMs = analysis?.duration_ms ?? 0;
  const rangeMs = rangeEnd - rangeStart;

  const problem = problemFor(mode, selected, rangeMs, file);
  const warnings = warningsFor(mode, selected, rangeMs);

  async function pollEnrollment(first: EnrollmentState): Promise<EnrollmentState> {
    let current = first;
    for (let i = 0; i < MAX_POLLS && current.status === 'pending'; i += 1) {
      await new Promise((resolve) => setTimeout(resolve, POLL_MS));
      current = await api.getEnrollment(videoId, current.enrollment_id);
    }
    return current;
  }

  async function confirm() {
    if (busy || problem) return;
    setBusy(true);
    setSubmitError(null);
    setRefusal(null);
    try {
      let state: EnrollmentState;
      if (mode === 'voice' && selected) {
        state = await api.createEnrollment(videoId, { face_id: faceId, source: 'voice', voice_id: selected.voice_id });
      } else if (mode === 'range') {
        state = await api.createEnrollment(videoId, {
          face_id: faceId,
          source: 'range',
          start_ms: rangeStart,
          end_ms: rangeEnd,
        });
      } else if (file) {
        state = await api.createVoiceFileEnrollment(videoId, faceId, file);
      } else {
        return;
      }
      state = await pollEnrollment(state);
      setEnrollWarnings(state.warnings ?? []);
      if (state.status !== 'ready') {
        if (state.status === 'failed' && state.error?.code === 'ENROLLMENT_REFUSED') {
          setRefusal(state.error.message);
        } else {
          setSubmitError(state.error ?? new Error('enrollment did not finish'));
        }
        return;
      }
      requestId.current ??= newRequestId();
      const created = await api.createJob({
        video_id: videoId,
        enrollment_id: state.enrollment_id,
        client_request_id: `${requestId.current}:${state.enrollment_id}`,
      });
      onJobCreated(created.job_id);
    } catch (caught) {
      if (isApiError(caught) && caught.code === 'ENROLLMENT_REFUSED') setRefusal(caught.message);
      else setSubmitError(caught);
    } finally {
      setBusy(false);
    }
  }

  if (loadError) {
    const failure = describeError(loadError);
    return (
      <Card>
        <CardHead title="تأكيد الصوت" />
        <Notice
          tone="danger"
          title={failure.title}
          code={failure.code}
          action={
            <Button size="sm" variant="secondary" icon="restart" onClick={() => setAttempt((v) => v + 1)}>
              جرّب تاني
            </Button>
          }
        >
          {failure.detail}
        </Notice>
      </Card>
    );
  }

  if (analysis?.status === 'failed') {
    return (
      <Card>
        <CardHead title="تأكيد الصوت" />
        <Notice
          tone="danger"
          title="معرفناش نحلل الأصوات في الفيديو"
          code={analysis.error?.code}
          action={
            <Button
              size="sm"
              variant="secondary"
              icon="restart"
              onClick={() => void api.retryAnalysis(videoId).then(() => setAttempt((v) => v + 1))}
            >
              جرّب تاني
            </Button>
          }
        >
          {analysis.error?.message ?? 'حصل خطأ أثناء تحليل الصوت.'}
        </Notice>
      </Card>
    );
  }

  if (!analysis || analysis.status === 'pending') {
    return (
      <Card>
        <CardHead title="تأكيد الصوت" hint="بنحلل الأصوات في الفيديو، الحالة هتتحدث لوحدها." />
        <div className="row">
          <Spinner />
          <p>بنحلل الأصوات…</p>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <CardHead
        title="أكّد صوت المتكلم"
        hint="اسمع كل صوت واختار الصوت اللي بيتكلم بيه الشخص اللي اخترته."
      />
      <div className="stack" dir="rtl">
        <Notice tone="info" title="ده اقتراح مش تأكيد">
          {suggestion?.note ?? 'الترتيب اقتراح فقط.'}{' '}
          {suggestion?.evidence === 'talk_time_only'
            ? 'مقدرناش نقيس ظهور الوجه، فالترتيب حسب مدة الكلام بس.'
            : null}
        </Notice>
        {suggestion?.notice ? <p className="hint">{suggestion.notice}</p> : null}

        <div className="row" role="tablist" aria-label="طريقة تحديد الصوت">
          <ModeTab mode="voice" current={mode} onSelect={setMode}>صوت من الفيديو</ModeTab>
          <ModeTab mode="range" current={mode} onSelect={setMode}>مدة بالوقت</ModeTab>
          <ModeTab mode="file" current={mode} onSelect={setMode}>تسجيل منفصل</ModeTab>
        </div>

        {mode === 'voice' ? (
          <ul className="stack" aria-label="الأصوات المكتشفة" style={{ listStyle: 'none', padding: 0 }}>
            {ordered.map((voice, index) => (
              <li key={voice.voice_id}>
                <VoiceRow
                  voice={voice}
                  ordinal={index + 1}
                  suggested={voice.voice_id === suggestedId}
                  selected={voice.voice_id === voiceId}
                  disabled={busy}
                  onSelect={() => setVoiceId(voice.voice_id)}
                />
              </li>
            ))}
          </ul>
        ) : null}

        {mode === 'range' ? (
          <div className="stack stack--tight">
            <p className="hint">
              حدّد مدة بيتكلم فيها الشخص ده لوحده، من {formatTimestamp(0)} إلى {formatTimestamp(durationMs)}.
            </p>
            <label className="label">
              البداية: {formatTimestamp(rangeStart)}
              <input
                type="range"
                min={0}
                max={durationMs}
                step={100}
                value={rangeStart}
                disabled={busy}
                aria-label="بداية المدة"
                onChange={(e) => setRangeStart(Math.min(Number(e.target.value), rangeEnd))}
              />
            </label>
            <label className="label">
              النهاية: {formatTimestamp(rangeEnd)}
              <input
                type="range"
                min={0}
                max={durationMs}
                step={100}
                value={rangeEnd}
                disabled={busy}
                aria-label="نهاية المدة"
                onChange={(e) => setRangeEnd(Math.max(Number(e.target.value), rangeStart))}
              />
            </label>
            <p className="hint">المدة المختارة: {(rangeMs / 1000).toFixed(1)} ثانية</p>
          </div>
        ) : null}

        {mode === 'file' ? (
          <div className="stack stack--tight">
            <p className="hint">ارفع تسجيل صوتي للشخص ده لوحده (٤ ثواني على الأقل، من غير أصوات تانية).</p>
            <input
              type="file"
              accept="audio/*"
              aria-label="ملف الصوت"
              disabled={busy}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
        ) : null}

        {warnings.map((text) => (
          <Notice key={text} tone="warn" title="تنبيه">
            {text}
          </Notice>
        ))}
        {problem ? (
          <Notice tone="danger" title="مش هينفع نكمل بالاختيار ده">
            {problem}
          </Notice>
        ) : null}
        {refusal ? (
          <Notice tone="danger" title="الخادم رفض العيّنة دي">
            {refusal}
          </Notice>
        ) : null}
        {enrollWarnings.length > 0 ? <p className="hint">{enrollWarnings.join(' · ')}</p> : null}
        {submitError ? (
          <Notice tone="danger" title={describeError(submitError).title} code={describeError(submitError).code}>
            {describeError(submitError).detail}
          </Notice>
        ) : null}

        <div className="row row--between">
          {onBack ? (
            <Button variant="ghost" onClick={onBack} disabled={busy}>
              رجوع لاختيار الوجه
            </Button>
          ) : (
            <span />
          )}
          <Button
            variant="primary"
            iconEnd="arrow-left"
            onClick={() => void confirm()}
            disabled={Boolean(problem) || busy}
            loading={busy}
          >
            {mode === 'voice' && selected?.voice_id === suggestedId ? 'أكّد الصوت المقترح' : 'أكّد وابدأ عزل الصوت'}
          </Button>
        </div>
      </div>
    </Card>
  );
}

function ModeTab({
  mode,
  current,
  onSelect,
  children,
}: {
  mode: Mode;
  current: Mode;
  onSelect: (mode: Mode) => void;
  children: string;
}) {
  return (
    <Button
      size="sm"
      variant={mode === current ? 'primary' : 'secondary'}
      onClick={() => onSelect(mode)}
      aria-pressed={mode === current}
    >
      {children}
    </Button>
  );
}

function VoiceRow(props: {
  voice: VoiceCandidateInfo;
  ordinal: number;
  suggested: boolean;
  selected: boolean;
  disabled: boolean;
  onSelect: () => void;
}) {
  const { voice, ordinal, suggested, selected, disabled, onSelect } = props;
  return (
    <label className="face-card" data-selected={selected} data-disabled={disabled || !voice.usable}>
      <input
        type="radio"
        name="voice-candidate"
        className="visually-hidden"
        checked={selected}
        disabled={disabled || !voice.usable}
        onChange={onSelect}
      />
      <span className="row row--between">
        <strong>{`صوت ${ordinal}`}</strong>
        {suggested ? <Pill tone="ok">مقترح</Pill> : null}
      </span>
      <span className="hint">
        {`كلام نضيف: ${voice.clean_s.toFixed(1)} ثانية`}
        {voice.overlap_fraction > 0.05 ? ` · تداخل ${Math.round(voice.overlap_fraction * 100)}٪` : ''}
      </span>
      {voice.refusal ? <span className="hint">{voice.refusal}</span> : null}
      {voice.usable ? voice.warnings.map((w) => <span key={w} className="hint">{w}</span>) : null}
      <VoiceSample voice={voice} />
    </label>
  );
}

function VoiceSample({ voice }: { voice: VoiceCandidateInfo }) {
  const api = useApi();
  const [url, setUrl] = useState<string | null>(null);
  const [state, setState] = useState<'idle' | 'loading' | 'failed'>('idle');

  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url);
  }, [url]);

  if (!voice.sample_url) return null;
  const sampleUrl = voice.sample_url;

  async function load() {
    setState('loading');
    try {
      const blob = await api.fetchMedia(sampleUrl);
      setUrl(URL.createObjectURL(blob));
      setState('idle');
    } catch {
      setState('failed');
    }
  }

  return url ? (
    // eslint-disable-next-line jsx-a11y/media-has-caption
    <audio controls autoPlay src={url} aria-label="عيّنة الصوت" />
  ) : (
    <Button
      size="sm"
      variant="secondary"
      icon="play"
      loading={state === 'loading'}
      onClick={(event) => {
        event.preventDefault();
        void load();
      }}
    >
      {state === 'failed' ? 'تعذّر التشغيل، جرّب تاني' : 'اسمع العيّنة'}
    </Button>
  );
}

function orderVoices(voices: VoiceCandidateInfo[], suggestion: SuggestionResponse | null): VoiceCandidateInfo[] {
  if (!suggestion || suggestion.candidates.length === 0) return voices;
  const rank = new Map(suggestion.candidates.map((c) => [c.voice_id, c.rank]));
  return [...voices].sort((a, b) => (rank.get(a.voice_id) ?? 1e9) - (rank.get(b.voice_id) ?? 1e9));
}

/** Hard refusals: the button stays disabled. The server repeats every one of these checks. */
export function problemFor(
  mode: Mode,
  voice: VoiceCandidateInfo | null,
  rangeMs: number,
  file: File | null,
): string | null {
  if (mode === 'voice') {
    if (!voice) return 'اختار صوت من القايمة الأول.';
    if (!voice.usable) return voice.refusal ?? 'العيّنة دي قصيرة جدًا.';
    return null;
  }
  if (mode === 'range') {
    if (rangeMs < MIN_ENROLL_MS) return 'المدة قصيرة جدًا — لازم ٤ ثواني على الأقل.';
    if (rangeMs > MAX_RANGE_MS) return 'المدة طويلة — الحد الأقصى ٦٠ ثانية.';
    return null;
  }
  return file ? null : 'اختار ملف صوتي الأول.';
}

export function warningsFor(mode: Mode, voice: VoiceCandidateInfo | null, rangeMs: number): string[] {
  const out: string[] = [];
  if (mode === 'voice' && voice?.usable) {
    out.push(...voice.warnings);
    if (voice.clean_s < 8) out.push('العيّنة قصيرة، والمطابقة ممكن تبقى أقل دقة.');
    if (voice.overlap_fraction > 0.2) out.push('الصوت ده بيتداخل مع أصوات تانية في أجزاء من الفيديو.');
  }
  if (mode === 'range' && rangeMs >= MIN_ENROLL_MS && rangeMs < 8_000) {
    out.push('المدة قصيرة، والمطابقة ممكن تبقى أقل دقة. تأكد إن الشخص بيتكلم لوحده فيها.');
  }
  return Array.from(new Set(out));
}

function newRequestId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}
