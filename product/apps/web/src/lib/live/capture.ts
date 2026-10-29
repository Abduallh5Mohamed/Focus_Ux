/** Camera + microphone capture that releases the hardware when stopped. */
export interface CapturedChunk {
  seq: number;
  blob: Blob;
  captureStartMs: number;
  durationMs: number;
}

export interface Capture {
  stream: MediaStream;
  /** Wall-clock ms at which recording started (same clock as playback timestamps). */
  startedWallMs: number;
  /** Resolves after the final chunk was delivered and every track was stopped. */
  stop(): Promise<void>;
}

export function pickMimeType(): string | undefined {
  const candidates = ['video/webm;codecs=vp8,opus', 'video/webm;codecs=vp9,opus', 'video/webm'];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type));
}

export async function startCapture(options: {
  chunkMs: number;
  onChunk: (chunk: CapturedChunk) => void;
  onError: (message: string) => void;
}): Promise<Capture> {
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    throw new Error('المتصفح ده مش بيدعم التسجيل من الكاميرا.');
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 640 }, height: { ideal: 360 }, frameRate: { ideal: 25 } },
    audio: { echoCancellation: true, noiseSuppression: true },
  });
  const releaseTracks = () => stream.getTracks().forEach((track) => track.stop());
  const mimeType = pickMimeType();
  if (!mimeType) {
    releaseTracks();
    throw new Error('المتصفح ده مش بيسجل WebM.');
  }
  const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 800_000 });
  const startedPerf = performance.now();
  const startedWallMs = Date.now();
  let seq = 0;
  let lastEnd = 0;

  const finished = new Promise<void>((resolve) => {
    recorder.onstop = () => {
      releaseTracks();
      resolve();
    };
  });
  recorder.ondataavailable = (event) => {
    if (!event.data || event.data.size === 0) return;
    const end = performance.now() - startedPerf;
    options.onChunk({
      seq: seq++, blob: event.data, captureStartMs: lastEnd, durationMs: Math.max(1, end - lastEnd),
    });
    lastEnd = end;
  };
  recorder.onerror = () => {
    options.onError('التسجيل وقف بسبب خطأ في المتصفح.');
    releaseTracks();
  };
  recorder.start(options.chunkMs);

  return {
    stream,
    startedWallMs,
    async stop() {
      if (recorder.state === 'inactive') {
        releaseTracks();
        return;
      }
      recorder.stop();
      await finished;
      releaseTracks();
    },
  };
}
