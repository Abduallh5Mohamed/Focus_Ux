import { K_AUDIO, K_FRAME, SAMPLE_RATE, type StreamRecord } from './streamProto';

export interface StreamCapture {
  stream: MediaStream;
  /** Wall-clock ms at which audio sample 0 was captured (same clock as playback rows). */
  wallOrigin: () => number;
  stop(): Promise<void>;
}

const WORKLET = `
class Tap extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) this.port.postMessage({ pcm: ch.slice(), t: currentTime });
    return true;
  }
}
registerProcessor('focus-tap', Tap);`;

const FLUSH_MS = 200;
const FRAME_MS = 40;
const JPEG_QUALITY = 0.6;

/**
 * Camera + mic as a continuous stream: PCM16 16 kHz audio with sample positions and
 * 25 fps JPEG frames stamped on the audio clock. Tracks are released on stop/error.
 */
export async function startStreamCapture(options: {
  onBatch: (records: StreamRecord[]) => void;
  onError: (message: string) => void;
  signal?: AbortSignal;
}): Promise<StreamCapture> {
  if (!navigator.mediaDevices?.getUserMedia || typeof AudioWorkletNode === 'undefined') {
    throw new Error('المتصفح ده مش بيدعم البث المباشر من الكاميرا.');
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 640 }, height: { ideal: 360 }, frameRate: { ideal: 25 } },
    audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
  });
  const release = () => stream.getTracks().forEach((t) => t.stop());
  if (options.signal?.aborted) {
    release();
    throw new DOMException('Capture cancelled', 'AbortError');
  }
  let ctx: AudioContext | null = null;
  let timers: number[] = [];
  try {
    ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
    const blobUrl = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
    await ctx.audioWorklet.addModule(blobUrl);
    URL.revokeObjectURL(blobUrl);
    const source = ctx.createMediaStreamSource(stream);
    const tap = new AudioWorkletNode(ctx, 'focus-tap');
    const mute = ctx.createGain(); // keep the graph pulled without playing the mic back
    mute.gain.value = 0;
    source.connect(tap).connect(mute).connect(ctx.destination);

    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.srcObject = new MediaStream(stream.getVideoTracks());
    await video.play();
    const canvas = document.createElement('canvas');
    const scale = Math.min(1, 640 / (video.videoWidth || 640));
    canvas.width = Math.round((video.videoWidth || 640) * scale);
    canvas.height = Math.round((video.videoHeight || 360) * scale);
    const g2d = canvas.getContext('2d');
    if (!g2d) throw new Error('تعذّر تجهيز التقاط الفريمات.');

    let t0: number | null = null;
    let wallOrigin = Date.now();
    let samples = 0;
    let audio: Int16Array[] = [];
    let audioStart = 0;
    const frames: StreamRecord[] = [];
    let closed = false;

    tap.port.onmessage = (event: MessageEvent<{ pcm: Float32Array; t: number }>) => {
      if (t0 === null) {
        t0 = event.data.t;
        wallOrigin = Date.now();
      }
      const f = event.data.pcm;
      const i16 = new Int16Array(f.length);
      for (let i = 0; i < f.length; i += 1) i16[i] = Math.max(-1, Math.min(1, f[i])) * 32767;
      audio.push(i16);
      samples += i16.length;
    };

    const flush = () => {
      const records: StreamRecord[] = [];
      if (audio.length) {
        const total = audio.reduce((n, a) => n + a.length, 0);
        const merged = new Int16Array(total);
        let off = 0;
        for (const a of audio) {
          merged.set(a, off);
          off += a.length;
        }
        records.push({ kind: K_AUDIO, position: audioStart, data: new Uint8Array(merged.buffer) });
        audioStart += total;
        audio = [];
      }
      records.push(...frames.splice(0));
      if (records.length) options.onBatch(records);
    };

    let busy = false;
    const grab = () => {
      if (closed || busy || t0 === null || !ctx) return;
      busy = true;
      g2d.drawImage(video, 0, 0, canvas.width, canvas.height);
      const ts = (ctx.currentTime - t0) * 1000;
      canvas.toBlob(async (blob) => {
        busy = false;
        if (!blob || closed) return;
        frames.push({ kind: K_FRAME, position: Math.max(0, ts), data: new Uint8Array(await blob.arrayBuffer()) });
      }, 'image/jpeg', JPEG_QUALITY);
    };
    timers = [window.setInterval(flush, FLUSH_MS), window.setInterval(grab, FRAME_MS)];
    stream.getTracks().forEach((t) => t.addEventListener('ended', () => {
      if (!closed) options.onError('الكاميرا أو المايك وقفوا.');
    }));
    void samples;

    return {
      stream,
      wallOrigin: () => wallOrigin,
      async stop() {
        if (closed) return;
        closed = true;
        timers.forEach((t) => window.clearInterval(t));
        flush(); // the last audio is delivered before the tracks are released
        release();
        await ctx?.close().catch(() => undefined);
      },
    };
  } catch (error) {
    timers.forEach((t) => window.clearInterval(t));
    release();
    await ctx?.close().catch(() => undefined);
    throw error;
  }
}
