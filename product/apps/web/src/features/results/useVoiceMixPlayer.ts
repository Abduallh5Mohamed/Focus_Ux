import { useCallback, useEffect, useRef, useState } from 'react';

import type { MixSettings } from '../../lib/api/types';

export type MixListen = 'original' | 'mix';

/** Same corner frequencies as the server (services/api/focus_api/mix.py). */
export const NOISE_FILTERS = {
  off: { high: 10, low: 20000 },
  light: { high: 100, low: 20000 },
  strong: { high: 150, low: 6000 },
} as const;

interface Buffers {
  voice: AudioBuffer | null;
  others: AudioBuffer | null;
}

const RAMP = 0.015;

/**
 * Live preview of the mix. The <video> element is the clock and the picture; the voice and
 * other-voices tracks play through Web Audio gain nodes. Moving a slider only changes a gain
 * value, so playback is never restarted. Switching original/mix mutes one side and unmutes
 * the other at the same instant, keeping the video's position.
 *
 * The browser limiter is a DynamicsCompressor approximation; the exported file uses the exact
 * server-side peak limiter.
 */
export function useVoiceMixPlayer(options: {
  videoRef: React.RefObject<HTMLVideoElement>;
  /** Changes when the <video> element is (re)created, so listeners re-attach. */
  videoUrl: string | null;
  buffers: Buffers;
  settings: MixSettings;
  listen: MixListen;
}) {
  const { videoRef, videoUrl, buffers, settings, listen } = options;
  const [supported] = useState(() => typeof window !== 'undefined' && 'AudioContext' in window);

  const ctxRef = useRef<AudioContext | null>(null);
  const graph = useRef<{
    voiceGain: GainNode;
    othersGain: GainNode;
    master: GainNode;
    high: BiquadFilterNode;
    low: BiquadFilterNode;
  } | null>(null);
  const sources = useRef<AudioBufferSourceNode[]>([]);
  const latest = useRef({ buffers, settings, listen });
  latest.current = { buffers, settings, listen };

  const ensureGraph = useCallback(() => {
    if (!supported) return null;
    if (!ctxRef.current) {
      const ctx = new window.AudioContext();
      const voiceGain = ctx.createGain();
      const othersGain = ctx.createGain();
      const high = ctx.createBiquadFilter();
      high.type = 'highpass';
      high.Q.value = Math.SQRT1_2;
      const low = ctx.createBiquadFilter();
      low.type = 'lowpass';
      low.Q.value = Math.SQRT1_2;
      const limiter = ctx.createDynamicsCompressor();
      limiter.threshold.value = -1;
      limiter.knee.value = 0;
      limiter.ratio.value = 20;
      limiter.attack.value = 0.003;
      limiter.release.value = 0.1;
      const master = ctx.createGain();
      voiceGain.connect(high);
      othersGain.connect(high);
      high.connect(low);
      low.connect(limiter);
      limiter.connect(master);
      master.connect(ctx.destination);
      ctxRef.current = ctx;
      graph.current = { voiceGain, othersGain, master, high, low };
    }
    return ctxRef.current;
  }, [supported]);

  const stopSources = useCallback(() => {
    for (const node of sources.current) {
      try {
        node.stop();
      } catch {
        /* already stopped */
      }
      node.disconnect();
    }
    sources.current = [];
  }, []);

  const startSources = useCallback(() => {
    const video = videoRef.current;
    const ctx = ensureGraph();
    const g = graph.current;
    if (!video || !ctx || !g) return;
    stopSources();
    if (video.paused || video.ended) return;
    void ctx.resume?.();
    const { voice, others } = latest.current.buffers;
    const rate = video.playbackRate || 1;
    const make = (buffer: AudioBuffer | null, target: GainNode) => {
      if (!buffer) return;
      const node = ctx.createBufferSource();
      node.buffer = buffer;
      node.playbackRate.value = rate;
      node.connect(target);
      node.start(0, Math.min(video.currentTime, Math.max(0, buffer.duration - 0.001)));
      sources.current.push(node);
    };
    make(voice, g.voiceGain);
    make(others, g.othersGain);
  }, [ensureGraph, stopSources, videoRef]);

  // Gains, filters and the original/mix switch: parameter changes only.
  useEffect(() => {
    const ctx = ensureGraph();
    const g = graph.current;
    const video = videoRef.current;
    if (!ctx || !g) {
      if (video) video.muted = listen === 'mix';
      return;
    }
    const now = ctx.currentTime;
    g.voiceGain.gain.setTargetAtTime(settings.voice_level, now, RAMP);
    g.othersGain.gain.setTargetAtTime(buffers.others ? settings.others_level : 0, now, RAMP);
    const filter = NOISE_FILTERS[settings.noise_reduction];
    g.high.frequency.setTargetAtTime(filter.high, now, RAMP);
    g.low.frequency.setTargetAtTime(Math.min(filter.low, ctx.sampleRate / 2 - 1), now, RAMP);
    g.master.gain.setTargetAtTime(listen === 'mix' ? 1 : 0, now, RAMP);
    if (video) video.muted = listen === 'mix';
  }, [ensureGraph, settings, buffers.others, listen, videoRef, videoUrl]);

  // Keep the buffer sources locked to the video clock.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const restart = () => startSources();
    const halt = () => stopSources();
    video.addEventListener('play', restart);
    video.addEventListener('playing', restart);
    video.addEventListener('seeked', restart);
    video.addEventListener('ratechange', restart);
    video.addEventListener('pause', halt);
    video.addEventListener('waiting', halt);
    video.addEventListener('seeking', halt);
    video.addEventListener('ended', halt);
    return () => {
      video.removeEventListener('play', restart);
      video.removeEventListener('playing', restart);
      video.removeEventListener('seeked', restart);
      video.removeEventListener('ratechange', restart);
      video.removeEventListener('pause', halt);
      video.removeEventListener('waiting', halt);
      video.removeEventListener('seeking', halt);
      video.removeEventListener('ended', halt);
    };
  }, [startSources, stopSources, videoRef, videoUrl]);

  // New tracks while playing: re-attach at the current position.
  useEffect(() => {
    startSources();
  }, [buffers.voice, buffers.others, startSources]);

  useEffect(
    () => () => {
      stopSources();
      void ctxRef.current?.close?.();
      ctxRef.current = null;
      graph.current = null;
    },
    [stopSources],
  );

  const decode = useCallback(
    async (blob: Blob): Promise<AudioBuffer> => {
      const ctx = ensureGraph();
      if (!ctx) throw new Error('web audio unavailable');
      return ctx.decodeAudioData(await blob.arrayBuffer());
    },
    [ensureGraph],
  );

  return { supported, decode };
}
