import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { APP_NAME } from '../lib/env';
import { useIsMockApi } from '../lib/api/ApiContext';
import { useOnline } from '../lib/useOnline';
import { BrandMark, Icon } from './Icon';
import { Pill } from './Pill';

/** App frame: header, offline/mock status, content, honest footer. */
export function AppShell({ children }: { children: ReactNode }) {
  const online = useOnline();
  const isMock = useIsMockApi();

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        تخطَّ إلى المحتوى
      </a>

      <header className="app__header">
        <Link to="/" className="app__brand" aria-label={`${APP_NAME} — الصفحة الرئيسية`}>
          <BrandMark className="app__brand-mark" />
          <span>{APP_NAME}</span>
        </Link>
        <span className="app__brand-sub">عزل صوت المتكلم</span>
        <span className="app__header-spacer" />
        <div className="app__header-actions">
          {isMock ? <Pill tone="warn">وضع تجريبي</Pill> : null}
          {!online ? (
            <Pill tone="danger">
              <Icon name="offline" size={12} /> بلا اتصال
            </Pill>
          ) : null}
        </div>
      </header>

      <main className="app__main" id="main">
        {!online ? (
          <div className="notice notice--warn" role="status" style={{ marginBottom: 'var(--sp-4)' }}>
            <Icon name="offline" size={18} />
            <div className="notice__body">
              <p className="notice__title">مفيش اتصال بالإنترنت</p>
              <p className="notice__text">
                الواجهة شغالة، لكن الرفع والمعالجة محتاجين اتصال بالخادم. مش بنعالج صوت على
                الجهاز.
              </p>
            </div>
          </div>
        ) : null}
        {children}
      </main>

      <footer className="app__footer">
        <p>
          المعالجة بتتم على خادم GPU، مش على جهازك. الصوت والنص بيتحذفوا لما تطلب حذف الطلب.
        </p>
      </footer>
    </div>
  );
}
