import { Link } from 'react-router-dom';

import { Card } from '../components/Card';

export function NotFoundPage() {
  return (
    <Card>
      <div className="stack">
        <h1 className="card__title">الصفحة مش موجودة</h1>
        <p className="card__hint">الرابط اللي فتحته مش معروف عندنا.</p>
        <p>
          <Link to="/">ارجع للصفحة الرئيسية</Link>
        </p>
      </div>
    </Card>
  );
}
