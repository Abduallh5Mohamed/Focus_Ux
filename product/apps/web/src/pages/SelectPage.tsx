import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { Button } from '../components/Button';
import { Card } from '../components/Card';
import { Notice } from '../components/Notice';
import { PageHeader } from '../components/PageHeader';
import { Spinner } from '../components/Spinner';
import { Steps } from '../components/Steps';
import { FaceSelect, VoiceConfirm } from '../features/input';
import { useApi } from '../lib/api/ApiContext';
import { describeError } from '../lib/api/errors';
import { saveSession } from '../lib/session';

export function SelectPage() {
  const { videoId } = useParams<{ videoId: string }>();
  const navigate = useNavigate();
  const api = useApi();
  const [engine, setEngine] = useState<string | null>(null);
  const [configError, setConfigError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const [chosenFace, setChosenFace] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setConfigError(null);
    api
      .getConfig(controller.signal)
      .then((config) => setEngine(config.engine))
      .catch((caught) => {
        if (!controller.signal.aborted) setConfigError(caught);
      });
    return () => controller.abort();
  }, [api, attempt]);

  if (!videoId) {
    return <p>الرابط ناقص.</p>;
  }

  const onJobCreated = (jobId: string) => {
    saveSession({ jobId });
    navigate(`/job/${jobId}`);
  };

  if (configError) {
    const failure = describeError(configError);
    return (
      <Card>
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

  if (!engine) {
    return (
      <div className="row">
        <Spinner />
        <p>بنجهّز الصفحة…</p>
      </div>
    );
  }

  const audioOnly = engine === 'audio_only';

  return (
    <>
      <Steps current={2} />
      {audioOnly && chosenFace ? (
        <>
          <PageHeader
            eyebrow="الخطوة 2"
            title="أكّد الصوت"
            lead="الوش بيحدد مين المتكلم، لكن العزل بيتم بالصوت بس. اسمع الأصوات المكتشفة وأكّد الصوت الصح."
          />
          <VoiceConfirm
            videoId={videoId}
            faceId={chosenFace}
            onJobCreated={onJobCreated}
            onBack={() => setChosenFace(null)}
          />
        </>
      ) : (
        <>
          <PageHeader
            eyebrow="الخطوة 2"
            title="اختار المتكلم"
            lead="دي الوجوه اللي اتكشفت في الفيديو. اختار الوش اللي عايز تعزل صوته — الترتيب مش دليل على الهوية."
          />
          <FaceSelect
            videoId={videoId}
            onJobCreated={onJobCreated}
            onFaceChosen={audioOnly ? setChosenFace : undefined}
          />
        </>
      )}
    </>
  );
}
