import { SAMPLE_RATE } from './streamProto';
import type { PlaybackReport, StreamPart } from './streamTypes';

const START_DELAY_S = 0.05;
const REBUFFER_PAD_S = 0.05;

/** Plays isolated parts in order on the capture timeline; silence for unusable parts. */
export class StreamPlayer {
  private ctx: AudioContext | null = null;
  private base: number | null = null; // ctx time at which sample 0 would play
  private rows = new Map<number, { capture_wall_ms: number; audible_wall_ms: number | null }>();
  private sources = new Set<AudioBufferSourceNode>();
  private seen = new Set<number>();
  private underruns = 0;
  rebuffers = 0;
  private closed = false;

  constructor(private readonly wallOrigin: () => number) {}

  private context(): AudioContext {
    if (!this.ctx) this.ctx = new AudioContext();
    return this.ctx;
  }

  async unlock(): Promise<void> {
    const ctx = this.context();
    if (ctx.state === 'suspended') await ctx.resume();
  }

  enqueue(part: StreamPart): void {
    if (this.closed || this.seen.has(part.idx)) return;
    this.seen.add(part.idx);
    const captureWall = this.wallOrigin() + (part.start / SAMPLE_RATE) * 1000;
    if (part.state !== 'ready' || !part.pcm) {
      this.underruns += 1;
      this.rows.set(part.idx, { capture_wall_ms: captureWall, audible_wall_ms: null });
      return;
    }
    const ctx = this.context();
    const offset = part.start / SAMPLE_RATE;
    if (this.base === null) this.base = ctx.currentTime + START_DELAY_S - offset;
    let startAt = this.base + offset;
    if (startAt < ctx.currentTime) {
      // Late: shift the whole timeline so later parts stay in order and never overlap.
      this.base += ctx.currentTime - startAt + REBUFFER_PAD_S;
      this.rebuffers += 1;
      startAt = this.base + offset;
    }
    const buffer = ctx.createBuffer(1, part.pcm.length, SAMPLE_RATE);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < part.pcm.length; i += 1) channel[i] = part.pcm[i] / 32768;
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    source.onended = () => this.sources.delete(source);
    this.sources.add(source);
    source.start(startAt);
    const outputLatency = (ctx.outputLatency || ctx.baseLatency || 0) * 1000;
    this.rows.set(part.idx, {
      capture_wall_ms: captureWall,
      audible_wall_ms: Date.now() + (startAt - ctx.currentTime) * 1000 + outputLatency,
    });
  }

  report(): PlaybackReport {
    return {
      chunks: [...this.rows.entries()].map(([seq, row]) => ({ seq, ...row })),
      underruns: this.underruns,
      rebuffers: this.rebuffers,
    };
  }

  close(): void {
    this.closed = true;
    for (const s of this.sources) {
      try {
        s.stop();
      } catch {
        /* already ended */
      }
    }
    this.sources.clear();
    void this.ctx?.close().catch(() => undefined);
    this.ctx = null;
  }
}
