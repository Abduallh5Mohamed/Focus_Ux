import type { OverlapRouting } from '../../lib/api/types';

export interface OverlapNote {
  tone: 'ok' | 'warn' | 'neutral';
  text: string;
}

const secs = (value: number): string => `${value.toFixed(1)} ث`;

/**
 * Plain-words note about what happened to overlapping speech. A continuity fallback
 * (the original mix played quietly) is never described as isolation.
 */
export function isolationModeLabel(routing: OverlapRouting | undefined): string | null {
  if (!routing?.mode) return null;
  return routing.mode === 'continuity'
    ? 'وضع الاستمرارية (مش عزل حقيقي)'
    : 'عزل صارم (الكلام المش مؤكد بيتكتم)';
}

export function overlapNote(routing: OverlapRouting | undefined): OverlapNote | null {
  if (!routing) return null;
  if (routing.overlap_extraction === 'failed' || routing.overlap_extraction === 'skipped') {
    const verb = routing.overlap_extraction === 'failed' ? 'فشل' : 'اتخطى';
    return {
      tone: 'warn',
      text: `استخراج الكلام المتداخل ${verb}${routing.reason ? ` (${routing.reason})` : ''}: النتيجة بدون استخراج حقيقي.${routing.fallback_used ? ' الصوت الأصلي اتسمع بصوت واطي، مش عزل.' : ''}`,
    };
  }
  if (routing.fallback_used) {
    return {
      tone: 'warn',
      text: `استمرارية بالصوت الأصلي، مش عزل: الصوت الأصلي اتسمع بصوت واطي لمدة ${secs(routing.fallback_seconds)}، وفيه أصوات تانية ممكن تتسمع.`,
    };
  }
  if (routing.target_may_be_lost && (routing.unconfirmed_seconds ?? 0) > 0) {
    return {
      tone: 'warn',
      text: `عزل صارم: ${secs(routing.unconfirmed_seconds ?? 0)} مش مؤكد إنه صوتك اتكتم، وممكن جزء من صوتك يكون ناقص هناك.`,
    };
  }
  if (routing.extractor_ran && routing.pieces_extracted > 0) {
    return {
      tone: 'ok',
      text: `الكلام المتداخل اتفصل بواسطة WeSep (${secs(routing.overlap_seconds)} متداخل، ${routing.pieces_extracted} جزء اتحفظ، ${routing.pieces_muted} جزء اتكتم).`,
    };
  }
  if (routing.extractor_ran) {
    return {
      tone: 'neutral',
      text: `الكلام المتداخل اتكتم: WeSep اشتغل على ${secs(routing.overlap_seconds)} لكن مفيش جزء اتأكد إنه صوتك.`,
    };
  }
  if (routing.extractor_requested) {
    return {
      tone: 'neutral',
      text: `الكلام المتداخل اتكتم: WeSep اتطلب بس ماشتغلش${routing.reason ? ` (${routing.reason})` : ''}.`,
    };
  }
  if (routing.overlap_seconds > 0 || routing.pieces_muted > 0) {
    return {
      tone: 'neutral',
      text: `الكلام المتداخل اتكتم (${secs(routing.overlap_seconds)}). مفيش عزل للكلام المتداخل في الوضع الافتراضي.`,
    };
  }
  return null;
}
