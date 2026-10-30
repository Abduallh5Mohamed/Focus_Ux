import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Card, CardHead } from '../../components/Card';
import { Notice } from '../../components/Notice';
import { Pill } from '../../components/Pill';
import { API_BASE_URL } from '../../lib/env';
import { createStreamApi, type StreamApi } from '../../lib/live/streamApi';
import { getToken } from '../../lib/session';
import { useLiveStream } from './useLiveStream';
import './live.css';

const PHASE_LABEL = {
  idle: 'جاهز', starting: 'بنبدأ…', recording: 'بيسجّل ويعزل', stopping: 'بنوقف…',
  finishing: 'بنخلص', done: 'خلص', error: 'خطأ',
} as const;

const PART_LABEL: Record<string, string> = {
  ready: 'متسمّع', target_lost: 'الوجه مش ظاهر', uncertain: 'مش متأكدين', failed: 'فشل',
};

/** Experimental continuous live mode: ~0.5 s hops on a sliding window, heard while recording. */
export function LiveStreamFlow({ streamApi }: { streamApi?: StreamApi }): JSX.Element {
  const api = useMemo(
    () => streamApi ?? createStreamApi({ baseUrl: API_BASE_URL, getToken }),
    [streamApi],
  );
  const { state, start, stop, selectTarget } = useLiveStream(api);
  const { phase, view, metrics } = state;
  const preview = useRef<HTMLVideoElement | null>(null);
  const [picked, setPicked] = useState<number | null>(null);

  useEffect(() => {
    if (preview.current) preview.current.srcObject = state.stream;
  }, [state.stream]);

  const recording = phase === 'recording';
  const unusable = ['target_lost', 'uncertain', 'failed'].filter((k) => state.partStates[k]);
  const counts = view?.counts ?? {};
  const lossy = Object.entries(counts).filter(([, n]) => n > 0);

  return (
    <div className="stack">
      <Notice tone="warn" title="وضع تجريبي مستمر">
        الصوت المعزول بيتسمع وانت بتسجّل بتأخير حوالي ثانية ونص (هدف لسه ما اتقاسش على الجهاز الحقيقي).
        استخدم سماعات عشان الصدى. الرفع العادي متاح دايمًا: <Link to="/upload">ارفع فيديو</Link>.
      </Notice>

      <Card>
        <CardHead title="البث من الكاميرا" action={<Pill tone={recording ? 'danger' : 'neutral'}>{PHASE_LABEL[phase]}</Pill>} />
        <div className="stack">
          <video ref={preview} className="live-preview" autoPlay muted playsInline aria-label="معاينة الكاميرا" />
          <div className="row">
            {phase === 'idle' || phase === 'error' || phase === 'done' ? (
              <Button variant="primary" onClick={() => void start()}>ابدأ البث</Button>
            ) : null}
            {recording ? <Button variant="danger" onClick={() => void stop()}>إيقاف</Button> : null}
          </div>
          {state.error ? <Notice tone="danger" title="حصلت مشكلة">{state.error}</Notice> : null}
        </div>
      </Card>

      {recording && view && !view.target_bbox ? (
        <Card>
          <CardHead title="اختار الشخص" hint="الاختيار بيحصل مرة واحدة، والتتبع بعدها مستمر." />
          {view.faces.length === 0 ? (
            <p className="hint">بندوّر على الوجوه…</p>
          ) : (
            <div className="stack">
              <div className="face-grid" role="radiogroup" aria-label="اختيار المتكلم">
                {view.faces.map((face, i) => (
                  <button
                    key={face.bbox.join(',')} type="button" role="radio" aria-checked={picked === i}
                    className={`face-option${picked === i ? ' face-option--selected' : ''}`}
                    onClick={() => setPicked(i)}
                  >
                    <img src={face.thumbnail_url} alt={`وجه ${i + 1} من ${view.faces.length}`} />
                  </button>
                ))}
              </div>
              <Button variant="primary" disabled={picked === null}
                onClick={() => picked !== null && void selectTarget(view.faces[picked].bbox)}>
                ابدأ السماع
              </Button>
            </div>
          )}
        </Card>
      ) : null}

      {view?.target_bbox && recording && state.partStates.target_lost ? (
        <Notice tone="warn" title="الوجه المختار مش ظاهر">الصوت المعزول واقف لحد ما الوجه يرجع.</Notice>
      ) : null}
      {unusable.length > 0 ? (
        <Notice tone="warn" title="أجزاء ملهاش صوت معزول">
          {unusable.map((k) => `${PART_LABEL[k]}: ${state.partStates[k]}`).join(' — ')}
        </Notice>
      ) : null}
      {state.sendFailures > 0 || lossy.length > 0 ? (
        <Notice tone="danger" title="في بيانات ضاعت أو اتكررت">
          دفعات فشل رفعها: {state.sendFailures}. {lossy.map(([k, n]) => `${k}: ${n}`).join('، ')}
        </Notice>
      ) : null}
      {state.rebuffers > 0 ? (
        <Notice tone="warn" title="الصوت اتأخر">بنأخر التشغيل عشان الأجزاء تتسمع بالترتيب من غير تداخل.</Notice>
      ) : null}
      {phase === 'finishing' ? <Notice tone="info" title="بنخلص آخر الأجزاء">الصوت المعزول الكامل بيجهز.</Notice> : null}

      {phase === 'done' ? (
        <Card>
          <CardHead title="النتيجة والقياس" />
          <div className="stack">
            {view?.audio_ready ? <p className="hint">الصوت المعزول الكامل اتحفظ على الخادم لمدة قصيرة. النص النهائي لسه مش موصّل في الوضع المستمر.</p> : null}
            {metrics ? (
              <>
                <dl className="facts" aria-label="لوحة القياس">
                  <Fact k="RTF (من العامل)" v={String(metrics.summary.rtf ?? 'مش مقاس')} />
                  <Fact k="التأخير للتشغيل (p95)" v={metrics.summary.capture_to_play_s?.p95 == null ? 'مش مقاس' : `${metrics.summary.capture_to_play_s.p95} ث`} />
                  <Fact k="أجزاء مفقودة" v={String(metrics.summary.parts_missing)} />
                  <Fact k="أجزاء مكررة" v={String(metrics.summary.parts_duplicated + (metrics.summary.playback?.duplicate_plays ?? 0))} />
                  <Fact k="مدة الجلسة" v={`${metrics.summary.session_s} ث`} />
                </dl>
                <Notice tone={metrics.gate.decision === 'enable_experimental' ? 'info' : 'warn'}
                  title={metrics.gate.decision === 'enable_experimental' ? 'عدّى البوابة (تجريبي)' : 'لسه داخلي'}>
                  {metrics.gate.reasons.join(' — ')}
                </Notice>
              </>
            ) : null}
          </div>
        </Card>
      ) : null}
    </div>
  );
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div className="facts__item">
      <dt className="facts__key">{k}</dt>
      <dd className="facts__val">{v}</dd>
    </div>
  );
}
