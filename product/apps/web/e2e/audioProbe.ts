import type { Page } from '@playwright/test';

/** Observe samples actually rendered by Chromium, without replacing its clock,
 * decoder, sources or scheduling. DC marker WAVs identify each chunk exactly. */
export async function installAudioProbe(page: Page) {
  await page.addInitScript(() => {
    const data = { starts: [] as { marker: number; at: number; duration: number }[],
      runs: [] as { marker: number; frame: number }[], frames: 0 };
    Object.assign(window, { audioProbe: data });
    const nativeCreate = AudioContext.prototype.createBufferSource;
    const probes = new WeakMap<AudioContext, ScriptProcessorNode>();
    AudioContext.prototype.createBufferSource = function () {
      let probe = probes.get(this);
      if (!probe) {
        probe = this.createScriptProcessor(1024, 1, 1);
        probe.onaudioprocess = (event) => {
          const samples = event.inputBuffer.getChannelData(0);
          for (let i = 0; i < samples.length; i++) {
            const marker = Math.round(samples[i] * 10);
            if (data.runs.at(-1)?.marker !== marker) data.runs.push({ marker, frame: data.frames + i });
          }
          data.frames += samples.length;
        };
        probe.connect(this.destination);
        probes.set(this, probe);
      }
      const source = nativeCreate.call(this);
      source.connect(probe);
      const start = source.start.bind(source);
      source.start = (at = 0, offset = 0, duration?: number) => {
        data.starts.push({ marker: Math.round((source.buffer?.getChannelData(0)[0] ?? 0) * 10),
          at, duration: duration ?? source.buffer?.duration ?? 0 });
        start(at, offset, duration);
      };
      return source;
    };
  });
}

export async function probe(page: Page) {
  return page.evaluate(() => (window as unknown as {
    audioProbe: { starts: { marker: number; at: number; duration: number }[];
      runs: { marker: number; frame: number }[]; frames: number };
  }).audioProbe);
}

/** Small valid PCM WAV generated in memory, not a fake decoder response. */
export function markerWav(marker: number, durationMs = 300): Buffer {
  const rate = 48000;
  const count = Math.round(rate * durationMs / 1000);
  const wav = Buffer.alloc(44 + count * 2);
  wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(rate, 24); wav.writeUInt32LE(rate * 2, 28);
  wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write('data', 36);
  wav.writeUInt32LE(count * 2, 40);
  for (let i = 0; i < count; i++) wav.writeInt16LE(Math.round(marker / 10 * 32767), 44 + i * 2);
  return wav;
}
