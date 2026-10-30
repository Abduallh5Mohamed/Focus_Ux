/**
 * DEV-ONLY mock adapter.
 *
 * Enabled exclusively when VITE_DEV_MOCK_API=1 (`npm run dev:mock`). The app shows a
 * permanent banner while it is active and never presents mock audio as real inference.
 * It exists so the UI can be built and reviewed before services/api is connected.
 */

import type {
  AudioStatus,
  CreateJobRequest,
  CreateJobResponse,
  FaceCandidate,
  FacesResponse,
  JobStage,
  JobState,
  JobStatus,
  TranscriptResponse,
  TranscriptStatus,
  UploadVideoResponse,
} from './types';
import type { FocusApi } from './client';

const MOCK_TOKEN = 'mock-session-token';
const MAX_FACES = 2;

interface MockVideo {
  id: string;
  createdAt: number;
  facesReadyAt: number;
  faces: FaceCandidate[];
}

interface MockJob {
  id: string;
  videoId: string;
  faceId: string;
  createdAt: number;
  clientRequestId: string;
}

interface MockJobView {
  status: JobStatus;
  stage: JobStage;
  audio: AudioStatus;
  transcript: TranscriptStatus;
  queuePosition: number;
}

const STAGE_PLAN: Array<{ at: number; view: Partial<MockJobView> }> = [
  { at: 0, view: { status: 'queued', stage: 'validating', queuePosition: 0 } },
  { at: 900, view: { status: 'processing', stage: 'preparing', queuePosition: 0 } },
  { at: 2_200, view: { status: 'processing', stage: 'tracking' } },
  { at: 4_600, view: { status: 'processing', stage: 'separating' } },
  { at: 6_400, view: { status: 'completed', stage: 'transcribing', audio: 'ready' } },
  { at: 8_400, view: { status: 'completed', stage: 'ready', transcript: 'ready' } },
];

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Dev/QA switch: when `focus-mock-transcript-fail=1` is set, the mock reports the
 * transcript as failed while keeping audio usable. Lets the browser QA exercise the
 * "transcript unavailable, audio still works" path without a real ASR provider.
 */
function transcriptFails(): boolean {
  try {
    return localStorage.getItem('focus-mock-transcript-fail') === '1';
  } catch {
    return false;
  }
}

function randomId(prefix: string): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${prefix}_${hex}`;
}

/** A tiny local placeholder so the mock never reaches for a network image. */
function placeholderThumbnail(label: string, hue: number): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="320" viewBox="0 0 320 320">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
  <stop offset="0" stop-color="hsl(${hue} 60% 26%)"/><stop offset="1" stop-color="hsl(${hue + 30} 70% 14%)"/>
  </linearGradient></defs>
  <rect width="320" height="320" fill="url(#g)"/>
  <circle cx="160" cy="132" r="58" fill="rgba(255,255,255,0.16)"/>
  <rect x="78" y="204" width="164" height="90" rx="45" fill="rgba(255,255,255,0.16)"/>
  <text x="160" y="308" font-family="sans-serif" font-size="22" fill="rgba(255,255,255,0.75)" text-anchor="middle">${label}</text>
</svg>`;
  return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`;
}

/** Builds a small mono WAV so the compare player has something audible to test. */
function buildMockWav(durationMs = 9_000, sampleRate = 16_000, baseHz = 196): Blob {
  const frames = Math.floor((durationMs / 1000) * sampleRate);
  const data = new Int16Array(frames);
  for (let i = 0; i < frames; i += 1) {
    const t = i / sampleRate;
    const gate = Math.sin(Math.PI * ((t * 1.2) % 1)) ** 2;
    const tone = Math.sin(2 * Math.PI * baseHz * t) * 0.22 + Math.sin(2 * Math.PI * baseHz * 2 * t) * 0.1;
    data[i] = Math.max(-1, Math.min(1, tone * gate)) * 0x7fff;
  }

  const buffer = new ArrayBuffer(44 + data.byteLength);
  const view = new DataView(buffer);
  const writeString = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i += 1) view.setUint8(offset + i, value.charCodeAt(i));
  };
  writeString(0, 'RIFF');
  view.setUint32(4, 36 + data.byteLength, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, 'data');
  view.setUint32(40, data.byteLength, true);
  new Int16Array(buffer, 44).set(data);

  return new Blob([buffer], { type: 'audio/wav' });
}

export interface MockApi extends FocusApi {
  /** Test hook: jump every pending job to its final state. */
  __completeAll(): void;
}

/**
 * The dev mock keeps its in-memory state across reloads via sessionStorage so the
 * after-refresh resume / original-comparison flows are exercisable. sessionStorage (not
 * localStorage) keeps each browser tab isolated, which is what the QA harness wants.
 * This is dev-only scaffolding; the real API persists on the server.
 */
const MOCK_PERSIST_KEY = 'focus-mock-state-v1';

function loadPersisted(): { videos: [string, MockVideo][]; jobs: [string, MockJob][] } | null {
  try {
    const raw = sessionStorage.getItem(MOCK_PERSIST_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { videos?: [string, MockVideo][]; jobs?: [string, MockJob][] };
    return { videos: parsed.videos ?? [], jobs: parsed.jobs ?? [] };
  } catch {
    return null;
  }
}

function savePersisted(videos: Map<string, MockVideo>, jobs: Map<string, MockJob>): void {
  try {
    const payload = { videos: [...videos.entries()], jobs: [...jobs.entries()] };
    sessionStorage.setItem(MOCK_PERSIST_KEY, JSON.stringify(payload));
  } catch {
    /* best-effort */
  }
}

export function createMockApi(options: { latencyMs?: number; facesReadyMs?: number } = {}): MockApi {
  const latency = options.latencyMs ?? 350;
  const facesReadyMs = options.facesReadyMs ?? 1_600;
  const initial = loadPersisted();
  const videos = new Map<string, MockVideo>(initial?.videos ?? []);
  const jobs = new Map<string, MockJob>(initial?.jobs ?? []);
  const byRequestId = new Map<string, string>();
  const forcedComplete = new Set<string>();
  const persist = () => savePersisted(videos, jobs);

  function jobView(job: MockJob): MockJobView {
    const view: MockJobView = {
      status: 'queued',
      stage: 'validating',
      audio: 'pending',
      transcript: 'pending',
      queuePosition: 0,
    };
    const elapsed = forcedComplete.has(job.id) ? Number.POSITIVE_INFINITY : Date.now() - job.createdAt;
    for (const step of STAGE_PLAN) {
      if (elapsed >= step.at) Object.assign(view, step.view);
    }
    if (transcriptFails() && elapsed >= 6_400) view.transcript = 'failed';
    return view;
  }

  function toJobState(job: MockJob): JobState {
    const view = jobView(job);
    return {
      job_id: job.id,
      status: view.status,
      stage: view.stage,
      selected_face_id: job.faceId,
      audio_status: view.audio,
      transcript_status: view.transcript,
      queue_position: view.queuePosition,
      error: null,
      result: view.audio === 'ready' ? { duration_ms: 9_000, sample_rate: 16_000, source_offset_ms: 0 } : null,
    };
  }

  function buildFaces(videoId: string): FaceCandidate[] {
    return Array.from({ length: MAX_FACES }, (_, index) => ({
      face_id: `${videoId}_face_${index + 1}`,
      thumbnail_url: placeholderThumbnail(`وجه ${index + 1}`, 186 + index * 42),
      bbox: { x: 120 + index * 220, y: 96, width: 168, height: 196 },
      timestamp_ms: 0,
      frame_size: { width: 1280, height: 720 },
    }));
  }

  return {
    baseUrl: 'mock://local',

    async uploadVideo(file, uploadOptions) {
      // Simulated progress so the upload UI can be reviewed.
      for (const step of [0.2, 0.55, 0.85, 1]) {
        await sleep(Math.max(60, latency / 2));
        uploadOptions?.onProgress?.(step);
      }
      if (uploadOptions?.signal?.aborted) throw new Error('aborted');

      const id = randomId('vid');
      videos.set(id, {
        id,
        createdAt: Date.now(),
        facesReadyAt: Date.now() + facesReadyMs,
        faces: buildFaces(id),
      });
      persist();

      const response: UploadVideoResponse = {
        video_id: id,
        session_token: MOCK_TOKEN,
        metadata: {
          duration_ms: 9_000,
          width: 1280,
          height: 720,
          fps: 25,
          mime_type: file.type || 'video/mp4',
          size_bytes: file.size,
        },
        faces_status: 'pending',
      };
      return response;
    },

    async getFaces(videoId) {
      await sleep(latency);
      const video = videos.get(videoId);
      if (!video) {
        return { status: 'failed', faces: [], error: { code: 'NOT_FOUND', message: 'فيديو غير موجود.', retryable: false } } satisfies FacesResponse;
      }
      if (Date.now() < video.facesReadyAt) {
        return { status: 'pending', faces: [] } satisfies FacesResponse;
      }
      return { status: 'ready', faces: video.faces } satisfies FacesResponse;
    },

    async createJob(input: CreateJobRequest) {
      await sleep(latency);
      const existing = byRequestId.get(input.client_request_id);
      if (existing) return { job_id: existing } satisfies CreateJobResponse;

      const id = randomId('job');
      jobs.set(id, {
        id,
        videoId: input.video_id,
        faceId: input.face_id,
        createdAt: Date.now(),
        clientRequestId: input.client_request_id,
      });
      byRequestId.set(input.client_request_id, id);
      persist();
      return { job_id: id } satisfies CreateJobResponse;
    },

    async getJob(jobId) {
      await sleep(Math.min(latency, 200));
      const job = jobs.get(jobId);
      if (!job) {
        throw new Error(`mock job ${jobId} not found`);
      }
      return toJobState(job);
    },

    async fetchAudio() {
      await sleep(latency);
      return buildMockWav();
    },

    async getTranscript(): Promise<TranscriptResponse> {
      await sleep(latency);
      if (transcriptFails()) {
        return {
          status: 'failed',
          segments: [],
          error: { code: 'TRANSCRIPT_FAILED', message: 'transcription provider unavailable', retryable: true },
        };
      }
      const segments = [
        { id: 's1', start_ms: 0, end_ms: 2_400, text: 'أهلًا بيكم، أنا هحكي عن نفسي باختصار.' },
        { id: 's2', start_ms: 2_600, end_ms: 5_100, text: 'أنا من القاهرة وبشتغل في مجال التصميم.' },
        { id: 's3', start_ms: 5_300, end_ms: 8_600, text: 'وبحب أقرأ وأتفرج على أفلام قديمة في وقت الفراغ.' },
      ];
      return { status: 'ready', segments };
    },

    async fetchMedia(url) {
      // Mock media are data:/blob: URLs only; never attach a token.
      const response = await fetch(url);
      return response.blob();
    },

    async fetchOriginal() {
      // Mock-only stand-in for GET /videos/{id}/original. Returns a clearly different tone
      // so the after-refresh compare path (fetch -> play) is exercisable in UI QA. The real
      // implementation streams the canonical uploaded bytes, not a synthesised clip.
      return buildMockWav(9_000, 16_000, 294);
    },

    async getMixInfo() {
      return {
        sample_rate: 48_000,
        others_available: true,
        others_unavailable_reason: null,
        alignment_ms: 0,
        level_gain: 1,
        correlation: 0.9,
        noise_filters: {},
      };
    },

    async fetchMixTrack() {
      return buildMockWav();
    },

    async startExport() {
      return { export_id: 'mock-export', status: 'ready' as const };
    },

    async getExport(_jobId, exportId) {
      return { export_id: exportId, status: 'ready' as const };
    },

    async fetchExport() {
      return new Blob(['mock'], { type: 'video/mp4' });
    },

    async deleteVideo(videoId) {
      await sleep(latency);
      videos.delete(videoId);
      for (const [jobId, job] of jobs) {
        if (job.videoId === videoId) jobs.delete(jobId);
      }
      persist();
      return { deletion_pending: true };
    },

    __completeAll() {
      for (const id of jobs.keys()) forcedComplete.add(id);
    },
  };
}
