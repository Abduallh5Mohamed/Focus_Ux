import { useNavigate, useParams } from 'react-router-dom';

import { PageHeader } from '../components/PageHeader';
import { Steps } from '../components/Steps';
import { FaceSelect } from '../features/input';
import { saveSession } from '../lib/session';

export function SelectPage() {
  const { videoId } = useParams<{ videoId: string }>();
  const navigate = useNavigate();

  if (!videoId) {
    return <p>الرابط ناقص.</p>;
  }

  return (
    <>
      <Steps current={2} />
      <PageHeader
        eyebrow="الخطوة 2"
        title="اختار المتكلم"
        lead="دي الوجوه اللي اتكشفت في الفيديو. اختار الوش اللي عايز تعزل صوته — الترتيب مش دليل على الهوية."
      />
      <FaceSelect
        videoId={videoId}
        onJobCreated={(jobId) => {
          saveSession({ jobId });
          navigate(`/job/${jobId}`);
        }}
      />
    </>
  );
}
