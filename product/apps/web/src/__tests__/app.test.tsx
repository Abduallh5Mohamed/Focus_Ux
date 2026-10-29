import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { App } from '../App';
import { ApiProvider } from '../lib/api/ApiContext';

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ApiProvider>
        <App />
      </ApiProvider>
    </MemoryRouter>,
  );
}

describe('app routes', () => {
  it('renders the landing page with the primary action', () => {
    renderAt('/');
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('افصل صوت');
    expect(screen.getByRole('button', { name: /ابدأ برفع فيديو/ })).toBeInTheDocument();
  });

  it('renders the upload step with a keyboard reachable drop zone', () => {
    renderAt('/upload');
    expect(screen.getByText('ارفع الفيديو')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /اختار فيديو أو اسحبه هنا/ })).toBeInTheDocument();
  });

  it('marks the current step in the step rail', () => {
    renderAt('/upload');
    const current = screen.getByRole('list', { name: 'مراحل العملية' }).querySelector('[aria-current="step"]');
    expect(current).toHaveTextContent('رفع الفيديو');
  });

  it('shows a not-found page for unknown routes', () => {
    renderAt('/nope');
    expect(screen.getByText('الصفحة مش موجودة')).toBeInTheDocument();
  });

  it('exposes a skip link to the main region', () => {
    renderAt('/');
    expect(screen.getByRole('link', { name: /تخطَّ إلى المحتوى/ })).toBeInTheDocument();
    expect(screen.getByRole('main')).toBeInTheDocument();
  });
});
