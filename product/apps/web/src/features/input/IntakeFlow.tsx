import { useEffect, useRef, useState } from 'react';

import { Button } from '../../components/Button';
import { Card, CardHead } from '../../components/Card';
import { Icon } from '../../components/Icon';
import { Notice } from '../../components/Notice';
import { ProgressBar } from '../../components/ProgressBar';
import { useApi } from '../../lib/api/ApiContext';
import { describeError, isApiError } from '../../lib/api/errors';
import { UPLOAD_LIMITS } from '../../lib/env';
import { clamp, formatBytes, formatDuration } from '../../lib/format';
import { rememberUpload } from '../../lib/localMedia';
import './input.css';

export interface IntakeFlowProps {
  /** Called once the server accepted the file and returned a video_id. */
  onUploaded: (videoId: string) => void;
}

/** A problem we detected in the browser. The server re-checks everything anyway. */
interface LocalProblem {
  title: string;
  detail: string;
}

const ACCEPTED_TYPES = UPLOAD_LIMITS.accept
  .split(',')
  .map((part) => part.trim().toLowerCase())
  .filter(Boolean);

const LIMITS_HINT = `حتى ${Math.round(UPLOAD_LIMITS.maxDurationMs / 1000)} ثانية و${Math.round(
  UPLOAD_LIMITS.maxBytes / (1024 * 1024),
)} ميجابايت.`;

const PROBE_TIMEOUT_MS = 8_000;

/**
 * Upload screen: pick a short clip, pre-check it locally, then stream it to the API.
 *
 * Pre-checks are advisory only — the server stays the final authority — so an unreadable
 * duration is allowed through instead of blocking a file we cannot measure.
 */
export function IntakeFlow(props: IntakeFlowProps): JSX.Element {
  const api = useApi();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [durationMs, setDurationMs] = useState<number | null>(null);
  const [durationUnknown, setDurationUnknown] = useState(false);
  const [probing, setProbing] = useState(false);
  const [problem, setProblem] = useState<LocalProblem | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [uploadError, setUploadError] = useState<unknown | null>(null);

  // Preview URL follows the chosen file and is always revoked with the file.
  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  // Duration probe. A container the browser cannot read is left to the server.
  useEffect(() => {
    if (!file) {
      setProbing(false);
      setDurationMs(null);
      setDurationUnknown(false);
      return;
    }

    let cancelled = false;
    const url = URL.createObjectURL(file);
    setProbing(true);
    setDurationMs(null);
    setDurationUnknown(false);

    void probeDurationMs(url).then((measured) => {
      if (cancelled) return;
      setProbing(false);
      if (measured === null) {
        setDurationUnknown(true);
        return;
      }
      setDurationMs(measured);
      if (measured > UPLOAD_LIMITS.maxDurationMs) {
        setProblem({
          title: 'مدة الفيديو أطول من الحد المسموح',
          detail: `المدة ${formatDuration(measured)}، والحد الأقصى ${formatDuration(
            UPLOAD_LIMITS.maxDurationMs,
          )}. قصّر الفيديو وجرّب تاني.`,
        });
      }
    });

    return () => {
      cancelled = true;
      URL.revokeObjectURL(url);
    };
  }, [file]);

  // A running upload must not outlive the screen.
  useEffect(
    () => () => {
      abortRef.current?.abort();
    },
    [],
  );

  function openPicker() {
    inputRef.current?.click();
  }

  function selectFile(next: File | undefined) {
    if (!next || uploading) return;

    setProblem(null);
    setUploadError(null);
    setProgress(0);

    if (next.size > UPLOAD_LIMITS.maxBytes) {
      setFile(null);
      setProblem({
        title: 'الملف أكبر من الحد المسموح',
        detail: `حجم الملف ${formatBytes(next.size)}، والحد الأقصى ${formatBytes(
          UPLOAD_LIMITS.maxBytes,
        )}. اختار ملف أصغر.`,
      });
      return;
    }

    if (!isAcceptedType(next)) {
      setFile(null);
      setProblem({
        title: 'صيغة الملف مش مدعومة',
        detail: 'المدعوم: MP4 أو MOV أو WebM أو MKV. حوّل الملف لصيغة من دول وجرّب تاني.',
      });
      return;
    }

    setFile(next);
  }

  function cancelUpload() {
    abortRef.current?.abort();
  }

  async function handleUpload() {
    if (!file || uploading || problem || probing) return;

    const controller = new AbortController();
    abortRef.current = controller;
    setUploading(true);
    setProgress(0);
    setUploadError(null);

    try {
      const response = await api.uploadVideo(file, {
        signal: controller.signal,
        onProgress: (fraction) => setProgress(clamp(fraction, 0, 1)),
      });
      if (controller.signal.aborted) return;
      rememberUpload(response.video_id, file);
      props.onUploaded(response.video_id);
    } catch (caught) {
      // A cancelled upload is not a failure: leave the file selected and say nothing.
      if (controller.signal.aborted || (isApiError(caught) && caught.code === 'ABORTED')) {
        setProgress(0);
        return;
      }
      setUploadError(caught);
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setUploading(false);
    }
  }

  const canUpload = Boolean(file) && !problem && !probing && !uploading;
  const uploadFailure = uploadError ? describeError(uploadError) : null;
  const percent = Math.round(progress * 100);

  return (
    <Card>
      <CardHead title="فيديو قصير فيه المتكلم" hint={LIMITS_HINT} />

      <div className="stack">
        <input
          ref={inputRef}
          type="file"
          accept={UPLOAD_LIMITS.accept}
          className="visually-hidden"
          tabIndex={-1}
          aria-hidden="true"
          onChange={(event) => {
            selectFile(event.target.files?.[0]);
            event.target.value = '';
          }}
        />

        <div
          className="stack"
          onDragEnter={(event) => {
            event.preventDefault();
            if (!uploading) setDragging(true);
          }}
          onDragOver={(event) => {
            event.preventDefault();
            if (!uploading) setDragging(true);
          }}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
          }}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            selectFile(event.dataTransfer.files?.[0]);
          }}
        >
          {file ? (
            <div className="stack">
              <div className="preview">
                {previewUrl ? (
                  <video
                    src={previewUrl}
                    controls
                    preload="metadata"
                    playsInline
                    aria-label={`معاينة الفيديو المختار: ${file.name}`}
                  />
                ) : null}
              </div>

              <dl className="facts intake-facts">
                <div className="facts__item">
                  <dt className="facts__key">الملف</dt>
                  <dd className="facts__val mono">{file.name}</dd>
                </div>
                <div className="facts__item">
                  <dt className="facts__key">الحجم</dt>
                  <dd className="facts__val">{formatBytes(file.size)}</dd>
                </div>
                <div className="facts__item">
                  <dt className="facts__key">المدة</dt>
                  <dd className="facts__val">
                    {probing
                      ? 'بنتحقق…'
                      : durationMs !== null
                        ? formatDuration(durationMs)
                        : durationUnknown
                          ? 'مش معروفة'
                          : '—'}
                  </dd>
                </div>
              </dl>

              {durationMs !== null && durationMs > 0 && durationMs < 1000 ? (
                <Notice tone="warn" title="الفيديو أقل من ثانية">
                  مدة الملف اللي اخترته {formatDuration(durationMs)} فقط. لو تقصد فيديو أطول،
                  راجع القص أو التصدير وغيّر الملف قبل الرفع.
                </Notice>
              ) : null}

              {durationUnknown ? (
                <p className="hint">
                  مقدرناش نقرا مدة الفيديو من المتصفح. مش هيتمنع الرفع — الخادم هيتحقق من المدة بنفسه.
                </p>
              ) : null}

              <div className="row">
                <Button
                  variant="primary"
                  icon="upload"
                  onClick={() => void handleUpload()}
                  disabled={!canUpload}
                  loading={uploading}
                >
                  {uploading ? 'بيترفع…' : 'ارفع وابدأ'}
                </Button>
                <Button variant="ghost" onClick={openPicker} disabled={uploading}>
                  تغيير الملف
                </Button>
                {uploading ? (
                  <Button variant="secondary" onClick={cancelUpload}>
                    إلغاء الرفع
                  </Button>
                ) : null}
              </div>

              <p className="hint">تقدر تسحب ملف تاني فوق المنطقة دي لتغييره.</p>
            </div>
          ) : (
            <button
              type="button"
              className="drop"
              data-dragging={dragging}
              onClick={openPicker}
              aria-describedby="intake-drop-hint"
            >
              <Icon name="upload" size={28} className="drop__icon" />
              <span className="drop__title">اختار فيديو أو اسحبه هنا</span>
              <span className="drop__hint" id="intake-drop-hint">
                {LIMITS_HINT} اضغط على المكان ده أو دوس Enter لفتح الملفات.
              </span>
            </button>
          )}
        </div>

        {problem ? (
          <Notice tone="danger" title={problem.title}>
            {problem.detail}
          </Notice>
        ) : null}

        {uploading ? (
          <div className="stack stack--tight">
            <ProgressBar value={progress} label="تقدّم رفع الفيديو" />
            <p className="hint" aria-live="polite">
              اترفع {percent}% من الملف… سيبه مفتوح لحد ما يخلص.
            </p>
          </div>
        ) : null}

        {uploadFailure ? (
          <Notice
            tone="danger"
            title={uploadFailure.title}
            code={uploadFailure.code}
            action={
              <Button size="sm" variant="secondary" icon="restart" onClick={() => void handleUpload()}>
                جرّب الرفع تاني
              </Button>
            }
          >
            {uploadFailure.detail}
          </Notice>
        ) : null}

        <p className="hint">
          الفحص هنا مبدئي عشان نوفر وقتك. الخادم هو المرجع النهائي في الصيغة والمدة ووجود الصوت.
        </p>
      </div>
    </Card>
  );
}

function isAcceptedType(file: File): boolean {
  const type = file.type.trim().toLowerCase();
  // Some containers (e.g. .mkv on Windows) arrive with an empty type; let the server judge.
  if (!type) return true;
  return ACCEPTED_TYPES.includes(type);
}

/**
 * Reads the duration through a detached <video>. Resolves null when the browser cannot
 * read metadata for this container, which is a "let the server decide" signal, not an error.
 */
function probeDurationMs(url: string): Promise<number | null> {
  return new Promise((resolve) => {
    const video = document.createElement('video');
    let settled = false;

    const finish = (value: number | null) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      video.onloadedmetadata = null;
      video.onerror = null;
      video.removeAttribute('src');
      resolve(value);
    };

    const timer = window.setTimeout(() => finish(null), PROBE_TIMEOUT_MS);

    video.preload = 'metadata';
    video.muted = true;
    video.onloadedmetadata = () => {
      const seconds = video.duration;
      finish(Number.isFinite(seconds) && seconds > 0 ? Math.round(seconds * 1000) : null);
    };
    video.onerror = () => finish(null);
    video.src = url;
  });
}
