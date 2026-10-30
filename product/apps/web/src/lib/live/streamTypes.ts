import type { ApiErrorPayload } from '../api/types';
import type { PlaybackReport } from './types';

export type StreamPhase = 'awaiting_worker' | 'awaiting_target' | 'live' | 'stopping' | 'done' | 'failed';
export type PartState = 'ready' | 'target_lost' | 'uncertain' | 'failed';

export interface StreamConfig {
  sample_rate: number;
  fps: number;
  window_s: number;
  hop_s: number;
  lookahead_s: number;
  crossfade_ms: number;
}

export interface StreamFace {
  bbox: [number, number, number, number];
  frame_size: [number, number];
  thumbnail_url: string;
}

export interface StreamView {
  live_session_id: string;
  phase: StreamPhase;
  config: StreamConfig;
  target_bbox: number[] | null;
  faces: StreamFace[];
  parts: number;
  error: ApiErrorPayload | null;
  counts: Record<string, number>;
  audio_ready: boolean;
}

export interface StreamPart {
  idx: number;
  start: number;
  samples: number;
  state: PartState;
  pcm: Int16Array | null;
}

export interface StreamMetrics {
  summary: {
    session_s: number;
    rtf: number | null;
    parts_total: number;
    parts_ready: number;
    parts_missing: number;
    parts_duplicated: number;
    capture_to_play_s: { n: number; median: number | null; p95: number | null; max: number | null } | null;
    playback: { underruns: number; rebuffers: number; duplicate_plays: number } | null;
  };
  gate: { decision: 'enable_experimental' | 'internal_only'; reasons: string[] };
}

export type { PlaybackReport };
