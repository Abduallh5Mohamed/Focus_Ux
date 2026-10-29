/**
 * Wire types for the FOCUS API.
 *
 * Source of truth: docs/02_CONTRACTS.md. Nothing here is invented beyond what that
 * document specifies; where the document is silent the field is optional and the UI
 * must not depend on it. Any change here is a contract change and needs Codex review.
 */

export type VideoId = string;
export type JobId = string;
export type FaceId = string;

export interface ApiErrorPayload {
  code: string;
  message: string;
  retryable: boolean;
}

/** Canonical rectangle in original-frame pixels. */
export interface BBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface FrameSize {
  width: number;
  height: number;
}

export interface VideoMetadata {
  duration_ms: number;
  width: number;
  height: number;
  fps?: number;
  mime_type?: string;
  size_bytes?: number;
}

export type FacesStatus = 'pending' | 'ready' | 'failed';

export interface UploadVideoResponse {
  video_id: VideoId;
  /** Present only on the first upload of a session. */
  session_token?: string;
  metadata: VideoMetadata;
  faces_status: FacesStatus;
}

export interface FaceCandidate {
  face_id: FaceId;
  /** Protected media URL: must be fetched with the session token, never used directly. */
  thumbnail_url: string;
  bbox: BBox;
  timestamp_ms: number;
  frame_size: FrameSize;
}

export interface FacesResponse {
  status: FacesStatus;
  faces: FaceCandidate[];
  error?: ApiErrorPayload | null;
}

export type JobStatus = 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled';

export type JobStage =
  | 'validating'
  | 'preparing'
  | 'tracking'
  | 'separating'
  | 'transcribing'
  | 'ready';

export type AudioStatus = 'pending' | 'ready' | 'failed';
export type TranscriptStatus = 'pending' | 'processing' | 'ready' | 'failed';

export type FollowState = 'visual' | 'voice_follow' | 'uncertain' | 'conflict';

export interface FollowPeriod {
  start_ms: number;
  end_ms: number;
  state: FollowState;
  reason: string;
  similarity?: number | null;
  output_allowed: boolean;
}

export interface JobResult {
  /** Optional: absent until the voice-follow models are approved and integrated. */
  follow_periods?: FollowPeriod[];
  duration_ms?: number;
  sample_rate?: number;
  source_offset_ms?: number;
  warnings?: string[];
}

export interface JobState {
  job_id: JobId;
  status: JobStatus;
  stage: JobStage;
  selected_face_id: FaceId;
  audio_status: AudioStatus;
  transcript_status: TranscriptStatus;
  queue_position: number;
  error: ApiErrorPayload | null;
  result: JobResult | null;
}

export interface CreateJobRequest {
  video_id: VideoId;
  face_id: FaceId;
  /** Idempotency key: retrying with the same value must not create a second job. */
  client_request_id: string;
}

export interface CreateJobResponse {
  job_id: JobId;
}

export interface TranscriptSegment {
  id: string;
  start_ms: number;
  end_ms: number;
  text: string;
}

export interface TranscriptResponse {
  status: TranscriptStatus;
  segments: TranscriptSegment[];
  error?: ApiErrorPayload | null;
}

export interface DeleteVideoResponse {
  deletion_pending?: boolean;
}

export const TERMINAL_JOB_STATUSES: readonly JobStatus[] = ['completed', 'failed', 'cancelled'];

export function isTerminalStatus(status: JobStatus): boolean {
  return TERMINAL_JOB_STATUSES.includes(status);
}

/** Human labels are UI text, kept next to the type so they never drift. */
export const JOB_STAGE_LABEL: Record<JobStage, string> = {
  validating: 'التحقق من الفيديو',
  preparing: 'تجهيز المدخل',
  tracking: 'تتبّع الوجه المختار',
  separating: 'عزل الصوت',
  transcribing: 'تفريغ النص',
  ready: 'جاهز',
};

export const JOB_STATUS_LABEL: Record<JobStatus, string> = {
  queued: 'في الانتظار',
  processing: 'قيد المعالجة',
  completed: 'تم',
  failed: 'فشل',
  cancelled: 'أُلغي',
};
