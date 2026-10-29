/** Normalised API failure. Every non-2xx response and every transport failure lands here. */

export type ApiErrorCode =
  | 'NETWORK'
  | 'TIMEOUT'
  | 'ABORTED'
  | 'UNAUTHORIZED'
  | 'NOT_FOUND'
  | 'LIMIT_EXCEEDED'
  | 'INVALID_MEDIA'
  | 'NO_AUDIO'
  | 'FACE_NOT_FOUND'
  | 'TARGET_LOST'
  | 'GPU_BUSY'
  | 'RATE_LIMITED'
  | 'SERVER_ERROR'
  | 'BAD_RESPONSE'
  | 'UNKNOWN';

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryable: boolean;

  constructor(params: {
    code: string;
    message: string;
    status?: number;
    retryable?: boolean;
    cause?: unknown;
  }) {
    super(params.message);
    this.name = 'ApiError';
    this.code = params.code;
    this.status = params.status ?? 0;
    this.retryable = params.retryable ?? false;
    if (params.cause !== undefined) {
      (this as { cause?: unknown }).cause = params.cause;
    }
  }

  /** True when the session is gone and the user must start over. */
  get isAuthFailure(): boolean {
    return this.code === 'UNAUTHORIZED';
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

const STATUS_FALLBACK: Record<number, { code: ApiErrorCode; retryable: boolean }> = {
  400: { code: 'INVALID_MEDIA', retryable: false },
  401: { code: 'UNAUTHORIZED', retryable: false },
  403: { code: 'UNAUTHORIZED', retryable: false },
  404: { code: 'NOT_FOUND', retryable: false },
  409: { code: 'GPU_BUSY', retryable: true },
  410: { code: 'NOT_FOUND', retryable: false },
  413: { code: 'LIMIT_EXCEEDED', retryable: false },
  415: { code: 'INVALID_MEDIA', retryable: false },
  422: { code: 'INVALID_MEDIA', retryable: false },
  429: { code: 'RATE_LIMITED', retryable: true },
  503: { code: 'GPU_BUSY', retryable: true },
};

export function apiErrorFromStatus(status: number, payload?: unknown): ApiError {
  const parsed = extractPayload(payload);
  if (parsed) {
    return new ApiError({
      code: parsed.code,
      message: parsed.message,
      status,
      retryable: parsed.retryable,
    });
  }

  const fallback = STATUS_FALLBACK[status] ?? {
    code: status >= 500 ? ('SERVER_ERROR' as ApiErrorCode) : ('UNKNOWN' as ApiErrorCode),
    retryable: status >= 500,
  };

  return new ApiError({
    code: fallback.code,
    message: DEFAULT_MESSAGE[fallback.code] ?? 'حدث خطأ غير متوقع.',
    status,
    retryable: fallback.retryable,
  });
}

function extractPayload(payload: unknown): { code: string; message: string; retryable: boolean } | null {
  if (!payload || typeof payload !== 'object') return null;
  const record = payload as Record<string, unknown>;
  const raw = (record.error ?? record) as Record<string, unknown>;
  if (typeof raw?.code !== 'string') return null;
  return {
    code: raw.code,
    message: typeof raw.message === 'string' ? raw.message : 'حدث خطأ غير متوقع.',
    retryable: raw.retryable === true,
  };
}

const DEFAULT_MESSAGE: Record<string, string> = {
  NETWORK: 'تعذّر الوصول للخادم. اتأكد من الاتصال وجرّب تاني.',
  TIMEOUT: 'الخادم اتأخر في الرد. جرّب تاني.',
  ABORTED: 'تم إلغاء الطلب.',
  UNAUTHORIZED: 'انتهت الجلسة. ابدأ برفع الفيديو من جديد.',
  NOT_FOUND: 'مش لاقيين الطلب ده. ممكن يكون اتحذف.',
  LIMIT_EXCEEDED: 'الملف أكبر من الحد المسموح.',
  INVALID_MEDIA: 'الملف مش فيديو صالح أو الصيغة مش مدعومة.',
  NO_AUDIO: 'الفيديو مفيهوش مسار صوت.',
  FACE_NOT_FOUND: 'مفيش وجه واضح في الفيديو.',
  TARGET_LOST: 'فقدنا الوجه المختار أثناء المعالجة.',
  GPU_BUSY: 'المعالجة مشغولة حاليًا. جرّب بعد شوية.',
  RATE_LIMITED: 'طلبات كتير في وقت قصير. استنى شوية.',
  SERVER_ERROR: 'حصل خطأ في الخادم. جرّب تاني.',
  BAD_RESPONSE: 'رد الخادم غير متوقع.',
  UNKNOWN: 'حدث خطأ غير متوقع.',
};

/** Arabic copy for a failure, safe for any unknown throwable. */
export function describeError(error: unknown): { title: string; detail: string; code?: string } {
  if (isApiError(error)) {
    return {
      title: DEFAULT_MESSAGE[error.code] ?? error.message,
      detail: error.retryable ? 'الخطأ قابل لإعادة المحاولة.' : 'لو استمر، ابدأ بملف جديد.',
      code: error.code,
    };
  }
  if (error instanceof Error) {
    return { title: 'حدث خطأ غير متوقع.', detail: error.message };
  }
  return { title: 'حدث خطأ غير متوقع.', detail: '' };
}
