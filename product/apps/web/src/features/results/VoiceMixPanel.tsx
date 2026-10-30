import { useEffect, useMemo, useRef, useState } from 'react';

import { Button } from '../../components/Button';
import { Card, CardHead } from '../../components/Card';
import { Notice } from '../../components/Notice';
import { Spinner } from '../../components/Spinner';
import { useApi } from '../../lib/api/ApiContext';
import { describeError } from '../../lib/api/errors';
import type { MixInfo, MixSettings, NoiseReduction } from '../../lib/api/types';
import { useMixExport } from './useMixExport';
import { useVoiceMixPlayer, type MixListen } from './useVoiceMixPlayer';
import './results.css';

interface VoiceMixPanelProps {
  jobId: string;
  /** Object URL of the original video (kept in memory or fetched from the server). */
  videoUrl: string | null;
  /** The isolated audio is ready; the mix needs it. */
  audioReady: boolean;
}

const DEFAULTS: MixSettings = { voice_level: 1, others_level: 0.25, noise_reduction: 'off' };

const NOISE_LABEL: Record<NoiseReduction, string> = {
  off: 'بدون',
  light: 'خفيف',
  strong: 'قوي',
};

const UNRELIABLE_MESSAGE =
  'مقدرناش نطلّع أصوات الباقيين بشكل موثوق، لأن الصوت المعزول مش متطابق في التوقيت أو المستوى مع صوت الفيديو الأصلي. ' +
  'عشان كده منزلق «الأصوات التانية» متعطّل، والمعاينة والتصدير بيستخدموا صوت الشخص المختار بس.';

export function VoiceMixPanel({ jobId, videoUrl, audioReady }: VoiceMixPanelProps): JSX.Element | null {
  const api = useApi();
  const videoRef = useRef<HTMLVideoElement>(null);

  const [settings, setSettings] = useState<MixSettings>(DEFAULTS);
  const [listen, setListen] = useState<MixListen>('mix');
  const [info, setInfo] = useState<MixInfo | null>(null);
  const [voice, setVoice] = useState<AudioBuffer | null>(null);
  const [others, setOthers] = useState<AudioBuffer | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [reload, setReload] = useState(0);

  const buffers = useMemo(() => ({ voice, others }), [voice, others]);
  const { supported, decode } = useVoiceMixPlayer({ videoRef, videoUrl, buffers, settings, listen });
  const exporter = useMixExport(jobId);

  useEffect(() => {
    if (!audioReady || !supported) return;
    const controller = new AbortController();
    setLoading(true);
    setLoadError(null);
    setInfo(null);
    setVoice(null);
    setOthers(null);
    (async () => {
      const mixInfo = await api.getMixInfo(jobId, controller.signal);
      const voiceBuffer = await decode(await api.fetchMixTrack(jobId, 'voice', controller.signal));
      const othersBuffer = mixInfo.others_available
        ? await decode(await api.fetchMixTrack(jobId, 'others', controller.signal))
        : null;
      if (controller.signal.aborted) return;
      setInfo(mixInfo);
      setVoice(voiceBuffer);
      setOthers(othersBuffer);
    })()
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setLoadError(caught);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [api, jobId, audioReady, supported, decode, reload]);

  if (!audioReady) return null;

  const othersAvailable = Boolean(info?.others_available);
  const failure = loadError ? describeError(loadError) : null;
  const exporting = exporter.phase === 'rendering' || exporter.phase === 'downloading';
  const exportFailure = exporter.error ? describeExportError(exporter.error) : null;

  function update(patch: Partial<MixSettings>) {
    setSettings((current) => ({ ...current, ...patch }));
  }

  function startExport() {
    // Never ask for a residual the server marked unreliable.
    void exporter.start({ ...settings, others_level: othersAvailable ? settings.others_level : 0 });
  }

  return (
    <Card>
      <CardHead
        title="ضبط الأصوات وتصدير الفيديو"
        hint="اسمع الفيديو نفسه، وبدّل بين صوته الأصلي والميكس الحالي في نفس اللحظة."
      />

      <div className="stack">
        {videoUrl ? (
          <video
            ref={videoRef}
            className="mix__video"
            src={videoUrl}
            controls
            muted={listen === 'mix'}
            playsInline
            preload="metadata"
            aria-label="فيديو المقارنة"
          />
        ) : (
          <p className="hint">الفيديو الأصلي مش متاح للمعاينة دلوقتي.</p>
        )}

        <div className="segmented" role="radiogroup" aria-label="اختار الصوت اللي تسمعه مع الفيديو">
          <button
            type="button"
            role="radio"
            aria-checked={listen === 'original'}
            className="segmented__btn"
            onClick={() => setListen('original')}
          >
            الصوت الأصلي
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={listen === 'mix'}
            className="segmented__btn"
            disabled={!voice}
            onClick={() => setListen('mix')}
          >
            الميكس الحالي
          </button>
        </div>

        {!supported ? (
          <Notice tone="warn" title="المتصفح مش بيدعم معاينة الميكس">
            تقدر لسه تصدّر الفيديو، لكن مش هتسمع التعديلات قبل التصدير.
          </Notice>
        ) : null}

        {loading ? (
          <div className="row" aria-live="polite">
            <Spinner />
            <span className="hint">بنجهّز مسارات الصوت…</span>
          </div>
        ) : null}

        {failure ? (
          <Notice
            tone="danger"
            title={failure.title}
            code={failure.code}
            action={
              <Button size="sm" icon="restart" onClick={() => setReload((value) => value + 1)}>
                جرّب تاني
              </Button>
            }
          >
            {failure.detail}
          </Notice>
        ) : null}

        {info && !othersAvailable ? (
          <Notice tone="warn" title="الأصوات التانية مش متاحة">
            {UNRELIABLE_MESSAGE}
          </Notice>
        ) : null}

        <div className="mix__controls">
          <label className="mix__control">
            <span className="mix__label">
              صوت الشخص المختار <span className="mono">{Math.round(settings.voice_level * 100)}%</span>
            </span>
            <input
              className="seek"
              type="range"
              min={0}
              max={2}
              step={0.05}
              value={settings.voice_level}
              onChange={(event) => update({ voice_level: Number(event.target.value) })}
              aria-label="مستوى صوت الشخص المختار"
            />
          </label>

          <label className="mix__control">
            <span className="mix__label">
              الأصوات التانية <span className="mono">{Math.round(settings.others_level * 100)}%</span>
            </span>
            <input
              className="seek"
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={othersAvailable ? settings.others_level : 0}
              onChange={(event) => update({ others_level: Number(event.target.value) })}
              disabled={!othersAvailable}
              aria-label="مستوى الأصوات التانية"
            />
          </label>

          <div className="mix__control" role="radiogroup" aria-label="تقليل الضوضاء">
            <span className="mix__label">تقليل الضوضاء (فلتر ترددات عادي، مش ذكاء اصطناعي)</span>
            <div className="segmented">
              {(Object.keys(NOISE_LABEL) as NoiseReduction[]).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  role="radio"
                  aria-checked={settings.noise_reduction === mode}
                  className="segmented__btn"
                  onClick={() => update({ noise_reduction: mode })}
                >
                  {NOISE_LABEL[mode]}
                </button>
              ))}
            </div>
          </div>
        </div>

        <p className="hint">
          الفلتر بيقص الترددات المنخفضة (والعالية في الوضع القوي) بس. مش بيفصل ضوضاء عن كلام. المعاينة في المتصفح
          تقريبية، والملف المصدّر هو النسخة الدقيقة وبيتحدد له سقف علو عشان ما يحصلش تشويه.
        </p>

        <div className="row">
          <Button
            variant="primary"
            icon="download"
            onClick={startExport}
            loading={exporting}
            disabled={!info}
          >
            تصدير الفيديو
          </Button>
          {exporter.phase === 'rendering' ? (
            <span className="hint" aria-live="polite">بنجهّز الفيديو الجديد…</span>
          ) : null}
          {exporter.phase === 'downloading' ? (
            <span className="hint" aria-live="polite">بننزّل الملف…</span>
          ) : null}
          {exporter.phase === 'done' && exporter.url ? (
            <a className="btn" href={exporter.url} download={`focus-${jobId}-mix.mp4`}>
              نزّل الفيديو (MP4)
            </a>
          ) : null}
        </div>

        {exportFailure ? (
          <Notice tone="danger" title={exportFailure.title} code={exportFailure.code}>
            {exportFailure.detail}
          </Notice>
        ) : null}
      </div>
    </Card>
  );
}

function describeExportError(error: unknown): { title: string; detail: string; code?: string } {
  const payload = (error as { exportError?: { code?: string; message?: string } }).exportError;
  if (payload?.code === 'EXPORT_UNSUPPORTED') {
    return {
      title: 'مقدرناش نصدّر الفيديو',
      detail: 'صورة الفيديو ده مينفعش تتنسخ جوه MP4 من غير ما تتغيّر، فمش هنعيد ترميزها.',
      code: payload.code,
    };
  }
  if (payload) {
    return { title: 'فشل تصدير الفيديو', detail: 'جرّب تصدّر تاني.', code: payload.code };
  }
  return describeError(error);
}
