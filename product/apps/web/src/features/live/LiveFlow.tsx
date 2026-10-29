import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Card, CardHead } from '../../components/Card';
import { Notice } from '../../components/Notice';
import { Pill } from '../../components/Pill';
import { useApi } from '../../lib/api/ApiContext';
import { API_BASE_URL } from '../../lib/env';
import { createLiveApi, type LiveApi } from '../../lib/live/liveApi';
import type { LiveChunkState } from '../../lib/live/types';
import { getToken } from '../../lib/session';
import type { FaceCandidate } from '../../lib/api/types';
import { FaceOption } from '../input';
import { useLiveSession } from './useLiveSession';
import './live.css';

const STATE_LABEL: Record<LiveChunkState, string> = {
  received: 'وصل',
  awaiting_target: 'مستني اختيار الشخص',
  queued: 'في الطابور',
  processing: 'بيتعالج',
  deferred: 'هيتعالج بعد التسجيل',
  ready: 'جاهز',
  missing: 'ناقص',
  target_lost: 'الوجه مش ظاهر',
  uncertain: 'مش متأكدين',
  failed: 'فشل',
  undecodable: 'مش مفهوم',
};

const BAD: LiveChunkState[] = ['missing', 'target_lost', 'uncertain', 'failed', 'undecodable'];

export interface LiveFlowProps {
  /** Test seam. */
  liveApi?: LiveApi;
}

/** Experimental near-live mode: record, pick the speaker, hear the isolated voice later. */
export function LiveFlow({ liveApi }: LiveFlowProps): JSX.Element {
  const api = useMemo(
    () => liveApi ?? createLiveApi({ baseUrl: API_BASE_URL, getToken }),
    [liveApi],
  );
  const { state, start, stop, selectTarget } = useLiveSession(api);
  const { phase, view } = state;
  const preview = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    if (preview.current) preview.current.srcObject = state.stream;
  }, [state.stream]);

  const recording = phase === 'recording';
  const overloaded = view?.mode === 'record_then_process';
  const bad = view?.chunks.filter((c) => BAD.includes(c.state)) ?? [];

  return (
    <div className="stack">
      <Notice tone="warn" title="وضع تجريبي بتأخير معلن">
        الصوت المعزول بيوصلك بتأخير حوالي ثواني بعد الكلام (الهدف التجريبي: ٣ ثواني أو أقل). مش مناسب
        للمحادثة. استخدم سماعات عشان الصدى. مسار الرفع العادي متاح دايمًا:{' '}
        <Link to="/upload">ارفع فيديو</Link>.
      </Notice>

      <Card>
        <CardHead
          title="التسجيل من الكاميرا"
          action={<Pill tone={recording ? 'danger' : 'neutral'}>{PHASE_LABEL[phase]}</Pill>}
        />
        <div className="stack">
          <video ref={preview} className="live-preview" autoPlay muted playsInline aria-label="معاينة الكاميرا" />
          <div className="row">
            {phase === 'idle' || phase === 'error' || phase === 'done' ? (
              <Button variant="primary" onClick={() => void start()}>
                ابدأ التسجيل
              </Button>
            ) : null}
            {recording ? (
              <Button variant="danger" onClick={() => void stop()}>
                إيقاف التسجيل
              </Button>
            ) : null}
          </div>
          {state.error ? (
            <Notice tone="danger" title="حصلت مشكلة">
              {state.error}
            </Notice>
          ) : null}
        </div>
      </Card>

      {view && !view.target_face_id && phase === 'recording' ? (
        <TargetPicker view={view} onPick={(id) => void selectTarget(id)} />
      ) : null}

      {overloaded ? (
        <Notice tone="warn" title="الحمل زائد: التحويل لوضع سجّل وبعدين عالج">
          المعالج مش لاحق. التسجيل مستمر والمقاطع الباقية هتتعالج بعد ما توقف، من غير ما أي صوت يضيع.
        </Notice>
      ) : null}

      {state.uploadFailures.length > 0 ? (
        <Notice tone="danger" title="مقاطع ما اترفعتش">
          المقاطع {state.uploadFailures.join('، ')} فشل رفعها وهتظهر ناقصة.
        </Notice>
      ) : null}

      {bad.length > 0 ? (
        <Notice tone="warn" title="في مقاطع ملهاش صوت معزول">
          {bad.map((c) => `#${c.seq}: ${STATE_LABEL[c.state]}`).join(' — ')}
        </Notice>
      ) : null}

      {state.rebuffers > 0 ? (
        <Notice tone="warn" title="الصوت اتأخر">
          بنأخر التشغيل عشان المقاطع تتسمع بالترتيب، من غير تداخل.
        </Notice>
      ) : null}

      {view ? (
        <Card>
          <CardHead title="المقاطع" hint={`عمق الطابور ${view.queue_depth} — إعادة تأخير التشغيل ${state.rebuffers}`} />
          <ol className="live-strip" aria-label="حالة المقاطع">
            {view.chunks.map((c) => (
              <li key={c.seq} className="live-chunk" data-state={c.state}>
                <span className="mono">{c.seq}</span>
                <span>{STATE_LABEL[c.state]}</span>
              </li>
            ))}
          </ol>
        </Card>
      ) : null}

      {phase === 'finishing' ? (
        <Notice tone="info" title="بنجهز النص النهائي على التسجيل كامل">
          ده بياخد وقت بعد الإيقاف. الصوت المعزول الكامل بيجهز معاه.
        </Notice>
      ) : null}

      {phase === 'done' && view ? <Done state={state} /> : null}
    </div>
  );
}

const PHASE_LABEL = {
  idle: 'جاهز',
  starting: 'بنبدأ…',
  recording: 'بيسجّل',
  stopping: 'بنوقف…',
  finishing: 'بنخلص',
  done: 'خلص',
  error: 'خطأ',
} as const;

function TargetPicker({
  view,
  onPick,
}: {
  view: NonNullable<ReturnType<typeof useLiveSession>['state']['view']>;
  onPick: (faceId: string) => void;
}) {
  const api = useApi();
  const [faces, setFaces] = useState<FaceCandidate[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const videoId = view.first_video_id;
  const ready = view.faces_status === 'ready';

  useEffect(() => {
    if (!videoId || !ready) return;
    let cancelled = false;
    void api.getFaces(videoId).then((r) => !cancelled && setFaces(r.faces)).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [api, videoId, ready]);

  if (view.faces_status === 'failed') {
    return <Notice tone="danger" title="معرفناش نكشف الوجوه في أول مقطع">وقّف وابدأ من جديد.</Notice>;
  }
  return (
    <Card>
      <CardHead title="اختار الشخص" hint="التسجيل شغال ومقاطعه بتتجمع لحد ما تختار." />
      {!ready || faces.length === 0 ? (
        <p className="hint">{ready ? 'مفيش وجه واضح في أول ثانيتين.' : 'بندوّر على الوجوه…'}</p>
      ) : (
        <div className="stack">
          <div className="face-grid" role="radiogroup" aria-label="اختيار المتكلم">
            {faces.map((face, i) => (
              <FaceOption
                key={face.face_id}
                face={face}
                ordinal={i + 1}
                total={faces.length}
                selected={selected === face.face_id}
                disabled={false}
                onSelect={setSelected}
              />
            ))}
          </div>
          <Button variant="primary" disabled={!selected} onClick={() => selected && onPick(selected)}>
            ابدأ السماع
          </Button>
        </div>
      )}
    </Card>
  );
}

function Done({ state }: { state: ReturnType<typeof useLiveSession>['state'] }) {
  const { view, metrics } = state;
  const final = view?.final;
  const m = metrics?.summary;
  const fmt = (v: number | null | undefined) => (v === null || v === undefined ? 'مش مقاس' : `${v} ث`);
  return (
    <Card>
      <CardHead title="النتيجة والقياس" />
      <div className="stack">
        {final?.status === 'ready' && final.job_id ? (
          <Link className="btn btn--primary" to={`/job/${final.job_id}/result`}>
            افتح النتيجة الكاملة والنص
          </Link>
        ) : (
          <Notice tone="danger" title="النتيجة النهائية فشلت">
            {final?.error?.message ?? 'مفيش تسجيل كامل جاهز.'}
          </Notice>
        )}
        {m ? (
          <dl className="facts" aria-label="لوحة القياس">
            <Fact k="التأخير من التسجيل للتشغيل (median)" v={fmt(m.capture_to_play_s?.median)} />
            <Fact k="التأخير من التسجيل للتشغيل (p95)" v={fmt(m.capture_to_play_s?.p95)} />
            <Fact k="أقصى عمق للطابور" v={String(m.max_queue_depth)} />
            <Fact k="مقاطع مفقودة" v={String(m.chunks_missing)} />
            <Fact k="مقاطع مكررة" v={String(m.chunks_duplicated + (m.playback?.duplicate_plays ?? 0))} />
            <Fact k="مدة الجلسة" v={fmt(m.session_s)} />
            <Fact k="RTF" v={m.rtf === null ? 'مش مقاس' : String(m.rtf)} />
          </dl>
        ) : null}
        {metrics ? (
          <Notice tone={metrics.gate.decision === 'enable_experimental' ? 'info' : 'warn'} title={
            metrics.gate.decision === 'enable_experimental' ? 'عدّى البوابة (تجريبي)' : 'لسه داخلي'
          }>
            {metrics.gate.reasons.join(' — ')}
          </Notice>
        ) : null}
      </div>
    </Card>
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
