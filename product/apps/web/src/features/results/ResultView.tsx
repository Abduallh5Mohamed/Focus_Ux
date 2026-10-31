import { useCallback, useEffect, useRef, useState } from 'react';

import { Button } from '../../components/Button';
import { Card, CardHead } from '../../components/Card';
import { Notice } from '../../components/Notice';
import { Pill } from '../../components/Pill';
import { useApi } from '../../lib/api/ApiContext';
import { describeError } from '../../lib/api/errors';
import type { JobState, TranscriptResponse } from '../../lib/api/types';
import { formatDuration, formatTimestamp } from '../../lib/format';
import { forgetUpload, getRememberedUpload } from '../../lib/localMedia';
import { ComparePlayer, type TrackMode } from './ComparePlayer';
import { isolationModeLabel, overlapNote } from './overlapNote';
import { VoiceMixPanel } from './VoiceMixPanel';
import { TranscriptPanel } from './TranscriptPanel';
import { useAudioTransport } from './useAudioTransport';
import './results.css';

export interface ResultViewProps {
  job: JobState;
  /** Video that owns the job, needed for DELETE /videos/{id}. May be null after a refresh. */
  videoId: string | null;
  /** Called after the server accepted the deletion. */
  onDeleted: () => void;
}

const ENGINE_LABELS: Record<string, string> = {
  dolphin: 'Dolphin',
  av_mossformer2: 'AV-MossFormer2',
  separate_select: 'فصل ثم اختيار المتكلم',
};

export function ResultView({ job, videoId, onDeleted }: ResultViewProps): JSX.Element {
  const api = useApi();

  const [mode, setMode] = useState<TrackMode>('isolated');
  const [isolatedUrl, setIsolatedUrl] = useState<string | null>(null);
  const [isolatedBlob, setIsolatedBlob] = useState<Blob | null>(null);
  const [isolatedLoading, setIsolatedLoading] = useState(false);
  const [isolatedError, setIsolatedError] = useState<unknown>(null);
  const [audioReload, setAudioReload] = useState(0);

  const [originalUrl, setOriginalUrl] = useState<string | null>(null);
  const [originalSource, setOriginalSource] = useState<'memory' | 'fetched' | null>(null);
  const [originalLoading, setOriginalLoading] = useState(false);
  const [originalError, setOriginalError] = useState<unknown>(null);
  const [originalReload, setOriginalReload] = useState(0);

  const [transcript, setTranscript] = useState<TranscriptResponse | null>(null);
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const [transcriptError, setTranscriptError] = useState<unknown>(null);
  const [transcriptReload, setTranscriptReload] = useState(0);

  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<unknown>(null);
  const deletingRef = useRef(false);

  const audioFailed = job.audio_status === 'failed';
  const isolatedReady = Boolean(isolatedUrl) && !audioFailed;

  /* ---------- original track ---------- */
  // Preferred source: the in-memory File we just uploaded (exact bytes, no extra download).
  useEffect(() => {
    const file = getRememberedUpload(videoId);
    if (!file) {
      setOriginalUrl(null);
      setOriginalSource(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setOriginalUrl(url);
    setOriginalSource('memory');
    return () => URL.revokeObjectURL(url);
  }, [videoId]);

  // Fallback source: after a refresh the in-memory File is gone, so fetch the canonical
  // original the server keeps (GET /videos/{id}/original). Only when nothing is in memory,
  // so we never download the same file twice.
  useEffect(() => {
    if (!videoId) return;
    if (getRememberedUpload(videoId)) return;

    const controller = new AbortController();
    let created: string | null = null;
    setOriginalUrl(null);
    setOriginalSource(null);
    setOriginalLoading(true);
    setOriginalError(null);

    api
      .fetchOriginal(videoId, controller.signal)
      .then((blob) => {
        if (controller.signal.aborted) return;
        created = URL.createObjectURL(blob);
        setOriginalUrl(created);
        setOriginalSource('fetched');
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setOriginalError(caught);
      })
      .finally(() => {
        if (!controller.signal.aborted) setOriginalLoading(false);
      });

    return () => {
      controller.abort();
      if (created) URL.revokeObjectURL(created);
    };
  }, [api, videoId, originalReload]);

  /* ---------- isolated track ---------- */
  useEffect(() => {
    if (job.audio_status !== 'ready') {
      setIsolatedLoading(false);
      return;
    }

    const controller = new AbortController();
    let created: string | null = null;
    // Reset first: the previous object URL is revoked by the cleanup below, so keeping it
    // in state would leave the player pointing at a dead blob after a failed reload.
    setIsolatedUrl(null);
    setIsolatedBlob(null);
    setIsolatedLoading(true);
    setIsolatedError(null);

    api
      .fetchAudio(job.job_id, controller.signal)
      .then((blob) => {
        if (controller.signal.aborted) return;
        created = URL.createObjectURL(blob);
        setIsolatedBlob(blob);
        setIsolatedUrl(created);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setIsolatedError(caught);
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsolatedLoading(false);
      });

    return () => {
      controller.abort();
      if (created) URL.revokeObjectURL(created);
    };
  }, [api, job.job_id, job.audio_status, audioReload]);

  /* ---------- transcript ---------- */
  useEffect(() => {
    const status = job.transcript_status;
    // The audio-only engine runs no speech recognition; there is nothing to fetch.
    if (job.transcript_enabled === false) return;
    if (status === 'pending' || status === 'processing') return;

    // Deps are primitives, so this only re-runs when the status or an explicit retry
    // changes. No key guard: under StrictMode a guard would abort the first fetch and
    // then skip the remount fetch, leaving the panel stuck "loading" forever.
    const controller = new AbortController();
    setTranscriptLoading(true);

    api
      .getTranscript(job.job_id, controller.signal)
      .then((response) => {
        if (controller.signal.aborted) return;
        setTranscript(response);
        setTranscriptError(null);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setTranscriptError(caught);
      })
      .finally(() => {
        if (!controller.signal.aborted) setTranscriptLoading(false);
      });

    return () => controller.abort();
  }, [api, job.job_id, job.transcript_status, job.transcript_enabled, transcriptReload]);

  /* ---------- default track ---------- */
  useEffect(() => {
    if (isolatedReady) setMode('isolated');
  }, [isolatedReady]);

  useEffect(() => {
    if (!isolatedReady && originalUrl) setMode('original');
  }, [isolatedReady, originalUrl]);

  const activeSrc = mode === 'isolated' ? isolatedUrl : originalUrl;
  const transport = useAudioTransport(activeSrc);

  const durationMs = job.result?.duration_ms ?? (transport.duration ? transport.duration * 1000 : undefined);
  const sampleRate = job.result?.sample_rate;

  const handleSeek = useCallback(
    (seconds: number) => {
      transport.seek(seconds);
    },
    [transport],
  );

  const downloadWav = useCallback(() => {
    if (!isolatedUrl) return;
    triggerDownload(isolatedUrl, `focus-${job.job_id}-isolated.wav`);
  }, [isolatedUrl, job.job_id]);

  const downloadTranscript = useCallback(() => {
    const segments = transcript?.segments ?? [];
    if (segments.length === 0) return;
    const text = segments
      .map((segment) => `[${formatTimestamp(segment.start_ms)}] ${segment.text}`)
      .join('\n');
    const blob = new Blob([`${text}\n`], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    triggerDownload(url, `focus-${job.job_id}-transcript.txt`);
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
  }, [transcript, job.job_id]);

  async function handleDelete() {
    if (!videoId || deletingRef.current) return;
    deletingRef.current = true;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteVideo(videoId);
      forgetUpload(videoId);
      onDeleted();
    } catch (caught) {
      setDeleteError(caught);
    } finally {
      deletingRef.current = false;
      setDeleting(false);
    }
  }

  const deleteFailure = deleteError ? describeError(deleteError) : null;

  return (
    <div className="stack stack--loose">
      {audioFailed ? (
        <Notice tone="danger" title="العزل فشل" code={job.error?.code}>
          {job.error?.message ?? 'الخادم مرجّعش صوت لهذا الطلب.'} تقدر تحذف الطلب وتبدأ من جديد.
        </Notice>
      ) : null}

      <ComparePlayer
        transport={transport}
        mode={mode}
        onModeChange={setMode}
        originalAvailable={Boolean(originalUrl)}
        originalSource={originalSource}
        originalLoading={originalLoading}
        originalError={originalError}
        onRetryOriginal={() => setOriginalReload((value) => value + 1)}
        isolatedReady={isolatedReady}
        isolatedLoading={isolatedLoading}
        isolatedError={isolatedError}
        onRetryIsolated={() => setAudioReload((value) => value + 1)}
        durationMs={durationMs}
        sampleRate={sampleRate}
        followPeriods={job.result?.follow_periods}
      />

      <VoiceMixPanel jobId={job.job_id} videoUrl={originalUrl} audioReady={job.audio_status === 'ready'} />

      <div className="grid-2">
        {job.transcript_enabled === false ? null : (
          <TranscriptPanel
            status={job.transcript_status}
            transcript={transcript}
            loading={transcriptLoading && !transcript}
            error={transcriptError}
            onRetry={() => setTranscriptReload((value) => value + 1)}
            currentTime={transport.currentTime}
            onSeek={handleSeek}
            onDownload={downloadTranscript}
          />
        )}

        <Card>
          <CardHead title="الملف" hint="نزّل الصوت المعزول أو احذف الطلب بالكامل. تصدير الفيديو بالميكس فوق." />

          <div className="stack">
            <dl className="facts">
              <div className="facts__item">
                <dt className="facts__key">المدة</dt>
                <dd className="facts__val">{formatDuration(durationMs)}</dd>
              </div>
              <div className="facts__item">
                <dt className="facts__key">معدل العينة</dt>
                <dd className="facts__val mono">{sampleRate ? `${sampleRate} Hz` : '—'}</dd>
              </div>
              <div className="facts__item">
                <dt className="facts__key">الوجه المختار</dt>
                <dd className="facts__val mono" title={job.selected_face_id}>
                  {shortId(job.selected_face_id)}
                </dd>
              </div>
              <div className="facts__item">
                <dt className="facts__key">حالة الصوت</dt>
                <dd className="facts__val">
                  {audioFailed ? 'فشل' : isolatedReady ? 'جاهز' : 'بيتجهز'}
                </dd>
              </div>
              {isolationModeLabel(job.result?.routing) ? (
                <div className="facts__item">
                  <dt className="facts__key">وضع العزل</dt>
                  <dd className="facts__val">{isolationModeLabel(job.result?.routing)}</dd>
                </div>
              ) : null}
              {job.result?.engine ? (
                <div className="facts__item">
                  <dt className="facts__key">محرك العزل</dt>
                  <dd className="facts__val mono">{ENGINE_LABELS[job.result.engine] ?? job.result.engine}</dd>
                </div>
              ) : null}
            </dl>

            {(() => {
              const note = overlapNote(job.result?.routing);
              return note ? (
                <Notice tone={note.tone === 'warn' ? 'warn' : 'info'} title={note.text} />
              ) : null;
            })()}

            <div className="row">
              <Button
                variant="primary"
                icon="download"
                onClick={downloadWav}
                disabled={!isolatedBlob}
              >
                تنزيل WAV
              </Button>
              <Pill tone={isolatedBlob ? 'ok' : 'neutral'}>
                {isolatedBlob ? 'WAV غير مضغوط' : 'مش جاهز'}
              </Pill>
            </div>

            <hr />

            <div className="stack stack--tight">
              <h3 className="card__title">حذف الطلب</h3>
              <p className="card__hint">
                الحذف بيشيل الفيديو والصوت والنص من الخادم. مش ممكن الرجوع فيه.
              </p>

              {!videoId ? (
                <p className="hint">
                  معرّف الفيديو مش متاح في الجلسة الحالية، فمش هنقدر نحذف من هنا. ابدأ بملف جديد
                  لو محتاج.
                </p>
              ) : null}

              {confirming ? (
                <div className="confirm" role="group" aria-label="تأكيد الحذف">
                  <p className="confirm__text">متأكد إنك عايز تحذف الطلب ده؟</p>
                  <div className="row">
                    <Button
                      variant="danger"
                      icon="trash"
                      onClick={() => void handleDelete()}
                      loading={deleting}
                      disabled={!videoId}
                    >
                      أيوه، احذف
                    </Button>
                    <Button variant="ghost" onClick={() => setConfirming(false)} disabled={deleting}>
                      إلغاء
                    </Button>
                  </div>
                </div>
              ) : (
                <Button
                  variant="danger"
                  icon="trash"
                  onClick={() => setConfirming(true)}
                  disabled={!videoId}
                >
                  حذف الطلب
                </Button>
              )}

              {deleteFailure ? (
                <Notice tone="danger" title={deleteFailure.title} code={deleteFailure.code}>
                  {deleteFailure.detail}
                </Notice>
              ) : null}
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function shortId(value: string): string {
  if (!value) return '—';
  return value.length <= 14 ? value : `${value.slice(0, 6)}…${value.slice(-4)}`;
}

function triggerDownload(url: string, filename: string): void {
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}
