import { describe, expect, it } from 'vitest';

import type { OverlapRouting } from '../../lib/api/types';
import { isolationModeLabel, overlapNote } from './overlapNote';

const base: OverlapRouting = {
  extractor_requested: 'wesep_bsrnn', extractor_ran: true, overlap_extraction: 'ran', reason: null,
  overlap_seconds: 4, windows: 2, pieces_extracted: 1, pieces_muted: 0, muted_seconds: 0,
  fallback_used: false, fallback_seconds: 0, isolation_claim: 'strict_isolation',
};

describe('overlapNote', () => {
  it('says nothing without routing data', () => expect(overlapNote(undefined)).toBeNull());
  it('names WeSep only when it ran and kept pieces', () => {
    expect(overlapNote(base)?.text).toContain('WeSep');
    expect(overlapNote(base)?.tone).toBe('ok');
  });
  it('never calls a fallback isolation', () => {
    const note = overlapNote({ ...base, fallback_used: true, fallback_seconds: 3, isolation_claim: 'not_isolation' });
    expect(note?.tone).toBe('warn');
    expect(note?.text).toContain('مش عزل');
  });
  it('labels the two modes and never calls continuity isolation', () => {
    expect(isolationModeLabel({ ...base, mode: 'continuity' })).toContain('مش عزل');
    expect(isolationModeLabel({ ...base, mode: 'strict' })).toContain('صارم');
    expect(isolationModeLabel(undefined)).toBeNull();
  });
  it('warns when strict mode may have lost target speech', () => {
    const note = overlapNote({ ...base, extractor_ran: false, overlap_extraction: 'disabled', pieces_extracted: 0,
      mode: 'strict', target_may_be_lost: true, unconfirmed_seconds: 2 });
    expect(note?.tone).toBe('warn');
    expect(note?.text).toContain('ناقص');
  });
  it('says plainly when extraction failed or was skipped', () => {
    expect(overlapNote({ ...base, overlap_extraction: 'failed', extractor_ran: false, reason: 'missing_weights' })?.text)
      .toContain('فشل');
    expect(overlapNote({ ...base, overlap_extraction: 'skipped', extractor_ran: false })?.tone).toBe('warn');
  });
  it('reports muted overlap when the extractor kept nothing', () => {
    expect(overlapNote({ ...base, pieces_extracted: 0, pieces_muted: 1 })?.text).toContain('اتكتم');
  });
});
