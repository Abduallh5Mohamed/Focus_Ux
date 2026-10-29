import { newPlan, planSlot, type PlanState } from './playbackPlan';
import type { PlaybackReport } from './types';

/** Web Audio player for isolated chunks. Records when each chunk becomes audible. */
export class LivePlayer {
  private ctx: AudioContext | null = null;
  private plan: PlanState = newPlan();
  private rows = new Map<number, { capture_wall_ms: number; audible_wall_ms: number | null }>();
  private sources = new Set<AudioBufferSourceNode>();
  private underruns = 0;

  constructor(private readonly captureWallOrigin: () => number) {}

  private context(): AudioContext {
    if (!this.ctx) this.ctx = new AudioContext();
    return this.ctx;
  }

  /** Must be called from a user gesture so playback is allowed to start. */
  async unlock(): Promise<void> {
    const ctx = this.context();
    if (ctx.state === 'suspended') await ctx.resume();
  }

  async enqueue(seq: number, captureStartMs: number, durationMs: number, wav: ArrayBuffer): Promise<void> {
    const ctx = this.context();
    const buffer = await ctx.decodeAudioData(wav.slice(0));
    const slot = planSlot(this.plan, seq, captureStartMs, ctx.currentTime);
    if (!slot) return;
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    source.onended = () => this.sources.delete(source);
    this.sources.add(source);
    source.start(slot.startAt, 0, Math.min(buffer.duration, durationMs / 1000));
    const outputLatency = (ctx.outputLatency || ctx.baseLatency || 0) * 1000;
    const audible = Date.now() + (slot.startAt - ctx.currentTime) * 1000 + outputLatency;
    this.rows.set(seq, {
      capture_wall_ms: this.captureWallOrigin() + captureStartMs,
      audible_wall_ms: audible,
    });
  }

  noteUnderrun(): void {
    this.underruns += 1;
  }

  get rebuffers(): number {
    return this.plan.rebuffers;
  }

  report(): PlaybackReport {
    return {
      chunks: [...this.rows.entries()].map(([seq, row]) => ({ seq, ...row })),
      underruns: this.underruns,
      rebuffers: this.plan.rebuffers,
    };
  }

  /** Stop everything now (used when the target changes or the screen closes). */
  close(): void {
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        /* already ended */
      }
    }
    this.sources.clear();
    void this.ctx?.close().catch(() => undefined);
    this.ctx = null;
  }
}
