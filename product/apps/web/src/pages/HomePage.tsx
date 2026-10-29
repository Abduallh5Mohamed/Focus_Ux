import { Link, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';

import { Button } from '../components/Button';
import { Card } from '../components/Card';
import { Icon } from '../components/Icon';
import { PageHeader } from '../components/PageHeader';
import { Pill } from '../components/Pill';
import { readSession, clearJob, type StoredSession } from '../lib/session';

const FLOW = [
  {
    icon: 'upload' as const,
    title: 'ارفع فيديو قصير',
    body: 'حتى 15 ثانية و50 ميجابايت. بنتحقق من الملف على الخادم قبل أي معالجة.',
  },
  {
    icon: 'user' as const,
    title: 'اختار المتكلم',
    body: 'بنعرضلك الوجوه اللي اتكشفت في الفيديو. تختار الوش، والمحرك يعزل صاحبه.',
  },
  {
    icon: 'wave' as const,
    title: 'اسمع وقارن',
    body: 'مشغل واحد تبدّل فيه بين الأصل والمعزول على نفس اللحظة، مع النص لو جاهز.',
  },
];

export function HomePage() {
  const navigate = useNavigate();
  const [session, setSession] = useState<StoredSession>(() => readSession());

  useEffect(() => {
    setSession(readSession());
  }, []);

  const canResume = Boolean(session.jobId);

  return (
    <>
      <PageHeader
        eyebrow="FOCUS"
        title="افصل صوت اللي بتسمعه"
        lead="ارفع مقطع فيديو، اختار الشخص اللي عايز تسمعه، وهنرجّعلك صوته لوحده — مع مقارنة مباشرة بالصوت الأصلي."
      />

      <Card>
        <div className="stack">
          <div className="row">
            <Button variant="primary" icon="upload" onClick={() => navigate('/upload')}>
              ابدأ برفع فيديو
            </Button>
            {canResume ? (
              <Button
                variant="ghost"
                icon="arrow-left"
                onClick={() => navigate(`/job/${session.jobId}`)}
              >
                رجوع للطلب الأخير
              </Button>
            ) : null}
          </div>

          {canResume ? (
            <div className="notice notice--info">
              <Icon name="clock" size={18} />
              <div className="notice__body">
                <p className="notice__title">عندك طلب مفتوح</p>
                <p className="notice__text">
                  لو قفلت الصفحة، تقدر ترجع لنفس الطلب من هنا. الطلب محفوظ في المتصفح ده بس.
                </p>
                <div className="row" style={{ marginTop: 'var(--sp-2)' }}>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      clearJob();
                      setSession(readSession());
                    }}
                  >
                    ابدأ من جديد
                  </Button>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </Card>

      <div className="grid-2" style={{ marginTop: 'var(--sp-4)' }}>
        {FLOW.map((item, index) => (
          <Card key={item.title} quiet>
            <div className="stack stack--tight">
              <div className="row">
                <Pill tone={index === 0 ? 'info' : 'neutral'}>{`الخطوة ${index + 1}`}</Pill>
                <Icon name={item.icon} size={18} />
              </div>
              <h2 className="card__title">{item.title}</h2>
              <p className="card__hint">{item.body}</p>
            </div>
          </Card>
        ))}
      </div>

      <Card quiet className="stack" >
        <div className="row">
          <Icon name="shield" size={18} />
          <p className="card__hint" style={{ flex: 1 }}>
            الملفات بتاعتك مرتبطة بجلسة المتصفح ده. تقدر تحذف الطلب في أي وقت، والملف والصوت
            والنص بيتشالوا مع بعض. مفيش حسابات ولا مشاركة عامة.
          </p>
        </div>
        <p className="card__hint">
          عايز تفاصيل أكتر؟ اقرأ <Link to="/upload">إرشادات الرفع</Link>.
        </p>
      </Card>
    </>
  );
}
