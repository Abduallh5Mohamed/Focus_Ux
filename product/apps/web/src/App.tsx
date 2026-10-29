import { Route, Routes } from 'react-router-dom';

import { AppShell } from './components/AppShell';
import { HomePage } from './pages/HomePage';
import { UploadPage } from './pages/UploadPage';
import { SelectPage } from './pages/SelectPage';
import { ProcessPage } from './pages/ProcessPage';
import { ResultPage } from './pages/ResultPage';
import { LivePage } from './pages/LivePage';
import { NotFoundPage } from './pages/NotFoundPage';

export function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/live" element={<LivePage />} />
        <Route path="/select/:videoId" element={<SelectPage />} />
        <Route path="/job/:jobId" element={<ProcessPage />} />
        <Route path="/job/:jobId/result" element={<ResultPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </AppShell>
  );
}
