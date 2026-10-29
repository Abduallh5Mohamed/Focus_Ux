/**
 * Pure scheduling for continuous playback of 2 s chunks.
 *
 * Slots keep the capture timeline: slot(seq) = base + capture_start. A chunk that is
 * ready after its slot started pushes the whole timeline later (a counted rebuffer),
 * so audio is never dropped silently; missing chunks simply leave their slot empty
 * and the UI shows them as gaps.
 */
export interface PlanState {
  base: number | null;
  rebuffers: number;
  seen: Set<number>;
  duplicates: number;
}

export const PRE_ROLL_S = 0.25;
export const LATE_TOLERANCE_S = 0.02;

export function newPlan(): PlanState {
  return { base: null, rebuffers: 0, seen: new Set(), duplicates: 0 };
}

export interface Slot {
  startAt: number;
  rebuffered: boolean;
}

/** Returns null when this chunk was already scheduled (never played twice). */
export function planSlot(state: PlanState, seq: number, captureStartMs: number, now: number): Slot | null {
  if (state.seen.has(seq)) {
    state.duplicates += 1;
    return null;
  }
  state.seen.add(seq);
  const offset = captureStartMs / 1000;
  if (state.base === null) {
    state.base = now + PRE_ROLL_S - offset;
    return { startAt: now + PRE_ROLL_S, rebuffered: false };
  }
  let startAt = state.base + offset;
  let rebuffered = false;
  if (startAt < now + LATE_TOLERANCE_S) {
    const shift = now + PRE_ROLL_S - startAt;
    state.base += shift;
    startAt += shift;
    state.rebuffers += 1;
    rebuffered = true;
  }
  return { startAt, rebuffered };
}
