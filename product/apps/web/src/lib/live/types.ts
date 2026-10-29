import type { ApiErrorPayload } from '../api/types';

export type LiveChunkState =
  | 'received'
  | 'awaiting_target'
  | 'queued'
  | 'processing'
  | 'deferred'
  | 'ready'
  | 'missing'
  | 'target_lost'
  | 'uncertain'
  | 'failed'
  | 'undecodable';

export interface LiveChunkView {
  seq: number;
  state: LiveChunkState;
  capture_start_ms: number;
  duration_ms: number;
  error: ApiErrorPayload | null;
  warnings: string[];
}

export interface LiveSessionView {
  live_session_id: string;
  experimental: true;
  phase: 'awaiting_chunk' | 'awaiting_target' | 'live' | 'stopped' | 'finalizing' | 'done' | 'failed';
  mode: 'live' | 'record_then_process';
  chunk_ms: number;
  target_face_id: string | null;
  first_video_id: string | null;
  faces_status: 'pending' | 'ready' | 'failed';
  queue_depth: number;
  expected_seq: number;
  overload_at_seq: number | null;
  error: ApiErrorPayload | null;
  counts: { duplicates: number; out_of_order: number; late_rejected: number };
  chunks: LiveChunkView[];
  final: {
    status: 'pending' | 'ready' | 'failed' | null;
    video_id: string | null;
    job_id: string | null;
    error: ApiErrorPayload | null;
  };
}

export interface LiveCreateResponse {
  live_session_id: string;
  session_token?: string;
  chunk_ms: number;
  max_chunks: number;
}

export interface PlaybackReport {
  chunks: { seq: number; capture_wall_ms: number; audible_wall_ms: number | null }[];
  underruns: number;
  rebuffers: number;
}

export interface LiveMetrics {
  summary: {
    session_s: number;
    chunks_total: number;
    chunks_ready: number;
    chunks_missing: number;
    chunks_unusable: number;
    chunks_duplicated: number;
    rtf: number | null;
    max_queue_depth: number;
    overload_at_seq: number | null;
    capture_to_play_s: { n: number; median: number | null; p95: number | null; max: number | null } | null;
    playback: { underruns: number; rebuffers: number; duplicate_plays: number } | null;
  };
  gate: { decision: 'enable_experimental' | 'internal_only'; reasons: string[] };
}
