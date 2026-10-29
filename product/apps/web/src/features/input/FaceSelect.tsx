import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { Link } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Card, CardHead } from '../../components/Card';
import { EmptyState } from '../../components/EmptyState';
import { Icon } from '../../components/Icon';
import { Notice } from '../../components/Notice';
import { Pill } from '../../components/Pill';
import { Spinner } from '../../components/Spinner';
import { useApi } from '../../lib/api/ApiContext';
import { describeError, isApiError } from '../../lib/api/errors';
import type { FaceCandidate, FacesResponse } from '../../lib/api/types';
import { clamp, formatTimestamp } from '../../lib/format';
import './input.css';

export interface FaceSelectProps {
  videoId: string;
  /** Called after POST /jobs returns a job_id. */
  onJobCreated: (jobId: string) => void;
}

const POLL_DELAY_MS = 1_500;
const MAX_BACKOFF_MS = 8_000;
/** ~90s of polling, then we stop and say so instead of spinning forever. */
const MAX_ATTEMPTS = 60;

/**
 * Face picker: polls until detection settles, then lets the visitor choose a candidate.
 *
 * Selection is always the `face_id`; the position in the list is presentation only, and
 * the copy says so. The idempotency key is minted once per (video, face) pair so a retry
 * of the same choice can never create a second job.
 */
export function FaceSelect(props: FaceSelectProps): JSX.Element {
  const api = useApi();
  const { videoId, onJobCreated } = props;

  const [response, setResponse] = useState<FacesResponse | null>(null);
  const [transportError, setTransportError] = useState<unknown | null>(null);
  const [exhausted, setExhausted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<unknown | null>(null);
  const [attempt, setAttempt] = useState(0);

  const requestRef = useRef<{ key: string; id: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    let timer: number | undefined;
    let attempts = 0;
    let failures = 0;

    setLoading(true);
    setExhausted(false);
    setTransportError(null);
    setResponse(null);
    setSelectedId(null);

    const tick = async () => {
      attempts += 1;
      try {
        const next = await api.getFaces(videoId, controller.signal);
        if (cancelled) return;
        failures = 0;
        setResponse(next);
        setTransportError(null);
        setLoading(false);

        if (next.status !== 'pending') return;
        if (attempts >= MAX_ATTEMPTS) {
          setExhausted(true);
          return;
        }
        timer = window.setTimeout(() => void tick(), POLL_DELAY_MS);
      } catch (caught) {
        if (cancelled) return;
        if (isApiError(caught) && caught.code === 'ABORTED') return;

        failures += 1;
        setLoading(false);
        setTransportError(caught);

        if (attempts >= MAX_ATTEMPTS) {
          setExhausted(true);
          return;
        }
        const delay = Math.min(POLL_DELAY_MS * 2 ** (failures - 1), MAX_BACKOFF_MS);
        timer = window.setTimeout(() => void tick(), delay);
      }
    };

    void tick();

    return () => {
      cancelled = true;
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [api, videoId, attempt]);

  function retry() {
    setAttempt((value) => value + 1);
  }

  async function handleConfirm() {
    if (!selectedId || creating) return;

    // Same video + same face => same key, so a retry is idempotent.
    const key = `${videoId}:${selectedId}`;
    let entry = requestRef.current;
    if (!entry || entry.key !== key) {
      entry = { key, id: newRequestId() };
      requestRef.current = entry;
    }

    setCreating(true);
    setCreateError(null);
    try {
      const created = await api.createJob({
        video_id: videoId,
        face_id: selectedId,
        client_request_id: entry.id,
      });
      onJobCreated(created.job_id);
    } catch (caught) {
      setCreateError(caught);
    } finally {
      setCreating(false);
    }
  }

  const status = response?.status ?? null;
  const faces = response?.faces ?? [];
  const createFailure = createError ? describeError(createError) : null;
  const transportFailure = transportError ? describeError(transportError) : null;
  const liveMessage = describeLive(status, faces.length, exhausted);

  if (status === 'failed') {
    return (
      <Card>
        <CardHead title="كشف الوجوه" hint="الخادم رجع بخطأ أثناء تحليل الفيديو." />
        <div className="stack">
          <Notice
            tone="danger"
            title="معرفناش نكشف الوجوه في الفيديو"
            code={response?.error?.code ?? undefined}
            action={
              <div className="row">
                <Button size="sm" variant="secondary" icon="restart" onClick={retry}>
                  جرّب تاني
                </Button>
                <Link to="/upload">ارفع فيديو تاني</Link>
              </div>
            }
          >
            {response?.error?.message ?? 'حصل خطأ غير متوقع أثناء تحليل الفيديو.'}
          </Notice>
        </div>
      </Card>
    );
  }

  if (status === 'ready' && faces.length === 0) {
    return (
      <Card>
        <CardHead title="كشف الوجوه" />
        <EmptyState
          icon="user"
          title="مفيش وجه واضح في الفيديو"
          action={
            <Link to="/upload" className="btn btn--primary btn--sm">
              ارفع فيديو تاني
            </Link>
          }
        >
          جرّب مقطع فيه وش واحد ظاهر للكاميرا وإضاءة أحسن.
        </EmptyState>
      </Card>
    );
  }

  if (status === 'ready') {
    return (
      <Card>
        <CardHead
          title="اختار المتكلم"
          hint="الترتيب مش دليل على الهوية — بص على الصورة واختار الوجه اللي عايز تعزل صوته."
          action={<Pill tone="neutral">{faceCountLabel(faces.length)}</Pill>}
        />
        <div className="stack">
          <p className="visually-hidden" aria-live="polite">
            {liveMessage}
          </p>

          <div className="face-grid" role="radiogroup" aria-label="اختيار المتكلم من الوجوه المكتشفة">
            {faces.map((face, index) => (
              <FaceOption
                key={face.face_id}
                face={face}
                ordinal={index + 1}
                total={faces.length}
                selected={selectedId === face.face_id}
                disabled={creating}
                onSelect={setSelectedId}
              />
            ))}
          </div>

          <div className="row row--between">
            <p className="hint" aria-live="polite">
              {selectedId ? 'تم اختيار الوجه.' : 'لازم تختار وجه الأول عشان نبدأ.'}
            </p>
            <Button
              variant="primary"
              iconEnd="arrow-left"
              onClick={() => void handleConfirm()}
              disabled={!selectedId || creating}
              loading={creating}
            >
              ابدأ عزل الصوت
            </Button>
          </div>

          {createFailure ? (
            <Notice
              tone="danger"
              title={createFailure.title}
              code={createFailure.code}
              action={
                <Button
                  size="sm"
                  variant="secondary"
                  icon="restart"
                  onClick={() => void handleConfirm()}
                  disabled={!selectedId}
                >
                  جرّب تاني
                </Button>
              }
            >
              {createFailure.detail} إعادة المحاولة بنفس الوجه مش هتكرر الطلب.
            </Notice>
          ) : null}
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <CardHead title="كشف الوجوه" hint="بندوّر على الوجوه في الفيديو، الحالة هتتحدث لوحدها." />
      <div className="stack">
        <p className="visually-hidden" aria-live="polite">
          {liveMessage}
        </p>

        {exhausted ? (
          <Notice
            tone="warn"
            title="خد وقت أطول من المتوقع"
            action={
              <Button size="sm" variant="secondary" icon="restart" onClick={retry}>
                جرّب تاني
              </Button>
            }
          >
            بقالنا وقت طويل بنستنى نتيجة كشف الوجوه ومجتش. ممكن الفيديو تقيل أو الخدمة مشغولة.
          </Notice>
        ) : (
          <div className="stack stack--tight">
            <div className="row">
              <Spinner />
              <p>بندوّر على الوجوه في الفيديو…</p>
            </div>
            <p className="hint">ده بياخد ثواني عادة. مش محتاج تعمل حاجة.</p>
          </div>
        )}

        {transportFailure ? (
          <Notice
            tone="warn"
            title={transportFailure.title}
            code={transportFailure.code}
            action={
              exhausted ? null : (
                <Button size="sm" variant="ghost" icon="restart" onClick={retry}>
                  جرّب دلوقتي
                </Button>
              )
            }
          >
            {exhausted
              ? transportFailure.detail
              : 'بنحاول نعيد المحاولة تلقائيًا. لو الاستنى طال، جرّب يدويًا.'}
          </Notice>
        ) : null}

        {!exhausted ? (
          <div className="grid-2" aria-hidden="true">
            <div className="skeleton face-card__skeleton" />
            <div className="skeleton face-card__skeleton" />
          </div>
        ) : null}

        {!exhausted && loading ? (
          <p className="hint">لسه مستنيين أول رد من الخادم.</p>
        ) : null}
      </div>
    </Card>
  );
}

interface FaceOptionProps {
  face: FaceCandidate;
  ordinal: number;
  total: number;
  selected: boolean;
  disabled: boolean;
  onSelect: (faceId: string) => void;
}

function FaceOption({ face, ordinal, total, selected, disabled, onSelect }: FaceOptionProps) {
  return (
    <label className="face-card" data-selected={selected} data-disabled={disabled}>
      <input
        type="radio"
        name="face-candidate"
        className="visually-hidden"
        value={face.face_id}
        checked={selected}
        disabled={disabled}
        onChange={() => onSelect(face.face_id)}
      />
      <FaceThumbnail face={face} />
      <span className="face-card__meta">
        <span className="face-card__time">
          <Icon name="clock" size={14} />
          لقطة عند {formatTimestamp(face.timestamp_ms)}
        </span>
        <span className="visually-hidden">{`المرشّح ${ordinal} من ${total}`}</span>
      </span>
      {selected ? (
        <span className="face-card__check" aria-hidden="true">
          <Icon name="check" size={14} />
        </span>
      ) : null}
    </label>
  );
}

function FaceThumbnail({ face }: { face: FaceCandidate }) {
  const api = useApi();
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setUrl(null);
    setFailed(false);

    api
      .fetchMedia(face.thumbnail_url, controller.signal)
      .then((blob) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setFailed(true);
      });

    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [api, face.thumbnail_url]);

  const aspect = frameAspect(face);
  const box = bboxStyle(face);

  return (
    <div className="face-card__thumb" style={aspect ? { aspectRatio: aspect } : undefined}>
      {failed ? (
        <div className="face-card__fallback">
          <Icon name="user" size={26} />
          <span className="hint">الصورة مش متاحة</span>
        </div>
      ) : url ? (
        <>
          <img src={url} alt="" />
          {box ? <span className="face-card__bbox" style={box} aria-hidden="true" /> : null}
        </>
      ) : (
        <div className="skeleton face-card__skeleton" aria-hidden="true" />
      )}
    </div>
  );
}

/**
 * The card box mirrors the source frame so the bbox percentages line up. Clamped so a
 * portrait clip cannot produce an unusable column of very tall cards.
 */
function frameAspect(face: FaceCandidate): string | undefined {
  const { width, height } = face.frame_size;
  if (!(width > 0) || !(height > 0)) return undefined;
  return String(clamp(width / height, 0.6, 2.4));
}

/** bbox/frame_size as clamped percentages; null when the frame size is unusable. */
function bboxStyle(face: FaceCandidate): CSSProperties | null {
  const { width: frameWidth, height: frameHeight } = face.frame_size;
  if (!(frameWidth > 0) || !(frameHeight > 0)) return null;

  const { x, y, width, height } = face.bbox;
  if (!(width > 0) || !(height > 0)) return null;

  const left = clamp((x / frameWidth) * 100, 0, 100);
  const top = clamp((y / frameHeight) * 100, 0, 100);
  const boxWidth = clamp((width / frameWidth) * 100, 0, 100 - left);
  const boxHeight = clamp((height / frameHeight) * 100, 0, 100 - top);

  return {
    left: `${left}%`,
    top: `${top}%`,
    width: `${boxWidth}%`,
    height: `${boxHeight}%`,
  };
}

function faceCountLabel(count: number): string {
  return count === 1 ? 'وجه واحد' : `${count} وجوه`;
}

function describeLive(
  status: FacesResponse['status'] | null,
  count: number,
  exhausted: boolean,
): string {
  if (exhausted) return 'كشف الوجوه خد وقت أطول من المتوقع.';
  if (status === 'ready') {
    return count === 0 ? 'مفيش وجه واضح في الفيديو.' : `لقينا ${faceCountLabel(count)}. اختار واحد.`;
  }
  if (status === 'failed') return 'فشل كشف الوجوه.';
  return 'بندوّر على الوجوه في الفيديو.';
}

function newRequestId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}
