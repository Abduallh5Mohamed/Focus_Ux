import { newPlan, planSlot, type PlanState } from './playbackPlan';
import type { LiveChunkView, PlaybackReport } from './types';

/** Web Audio player for isolated chunks. Records when each chunk becomes audible. */
export class LivePlayer {
  private ctx: AudioContext | null = null;
  private plan: PlanState = newPlan();
  private rows = new Map<number, { capture_wall_ms: number; audible_wall_ms: number | null }>();
  private sources = new Set<AudioBufferSourceNode>();
  private underruns = 0;
  private nextSeq = 0;
  private chunks = new Map<number, LiveChunkView>();
  private decoded = new Map<number, AudioBuffer>();
  private decoding = new Set<number>();
  private endAt = 0;
  private closed = false;

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

  /** Declare gaps before audio arrives. Unresolved predecessors block later audio. */
  updateChunks(chunks: LiveChunkView[]): void {
    if (this.closed) return;
    for (const chunk of chunks) {
      if (chunk.seq >= this.nextSeq) this.chunks.set(chunk.seq, chunk);
    }
    this.drain();
  }

  async enqueue(seq: number, captureStartMs: number, durationMs: number, wav: ArrayBuffer, signal?: AbortSignal): Promise<void> {
    if (this.closed || signal?.aborted || seq < this.nextSeq || this.decoding.has(seq) || this.decoded.has(seq)) return;
    const ctx = this.context();
    this.decoding.add(seq);
    try {
      const buffer = await ctx.decodeAudioData(wav.slice(0));
      if (this.closed || signal?.aborted || seq < this.nextSeq) return;
      this.chunks.set(seq, { seq, capture_start_ms: captureStartMs, duration_ms: durationMs,
        state: 'ready', error: null, warnings: [] });
      this.decoded.set(seq, buffer);
      this.drain();
    } finally {
      this.decoding.delete(seq);
    }
  }

  private drain(): void {
    if (this.closed) return;
    while (true) {
      const chunk = this.chunks.get(this.nextSeq);
      if (!chunk) return;
      if (['missing', 'target_lost', 'uncertain', 'failed', 'undecodable'].includes(chunk.state)) {
        this.noteUnderrun();
        this.rows.set(chunk.seq, {
          capture_wall_ms: this.captureWallOrigin() + chunk.capture_start_ms,
          audible_wall_ms: null,
        });
        this.decoded.delete(this.nextSeq);
        this.chunks.delete(this.nextSeq++);
        continue;
      }
      const buffer = this.decoded.get(this.nextSeq);
      if (!buffer) return;
      this.schedule(chunk, buffer);
      this.decoded.delete(this.nextSeq);
      this.chunks.delete(this.nextSeq++);
    }
  }

  /** Call after pending downloads/decodes settle. Unplayable chunks are explicit
   * null-audible rows, and cannot block later decoded audio from being measured. */
  finish(): void {
    if (this.closed) return;
    for (const [seq, chunk] of this.chunks) {
      if (!this.decoded.has(seq)) this.chunks.set(seq, { ...chunk, state: 'failed' });
    }
    this.drain();
  }

  private schedule(chunk: LiveChunkView, buffer: AudioBuffer): void {
    const ctx = this.context();
    const slot = planSlot(this.plan, chunk.seq, chunk.capture_start_ms, ctx.currentTime);
    if (!slot) return;
    // Rounding/variable recorder durations must never overlap the preceding source.
    if (slot.startAt < this.endAt) {
      this.plan.base! += this.endAt - slot.startAt;
      slot.startAt = this.endAt;
    }
    const duration = Math.min(buffer.duration, chunk.duration_ms / 1000);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    source.onended = () => this.sources.delete(source);
    this.sources.add(source);
    source.start(slot.startAt, 0, duration);
    this.endAt = slot.startAt + duration;
    const outputLatency = (ctx.outputLatency || ctx.baseLatency || 0) * 1000;
    const audible = Date.now() + (slot.startAt - ctx.currentTime) * 1000 + outputLatency;
    this.rows.set(chunk.seq, {
      capture_wall_ms: this.captureWallOrigin() + chunk.capture_start_ms,
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
    this.closed = true;
    this.decoded.clear();
    this.chunks.clear();
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
