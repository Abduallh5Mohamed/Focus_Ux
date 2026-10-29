import { useCallback, useEffect, useRef, useState } from 'react';

export interface AudioTransport {
  audioRef: React.RefObject<HTMLAudioElement>;
  playing: boolean;
  buffering: boolean;
  failed: boolean;
  currentTime: number;
  duration: number;
  toggle: () => void;
  pause: () => void;
  seek: (seconds: number) => void;
}

/**
 * Owns the single <audio> element used for both tracks.
 *
 * Switching `src` keeps the playhead: the previous position is captured before the source
 * changes and restored once metadata for the new track is available. That is what makes
 * "compare at the same moment" honest instead of restarting the clip each time.
 */
export function useAudioTransport(src: string | null): AudioTransport {
  const audioRef = useRef<HTMLAudioElement>(null);
  const pendingSeek = useRef<number | null>(null);

  const [playing, setPlaying] = useState(false);
  const [buffering, setBuffering] = useState(false);
  const [failed, setFailed] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  // Source changes: preserve position and playback intent.
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    if (!src) {
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
      setPlaying(false);
      setBuffering(false);
      setCurrentTime(0);
      setDuration(0);
      return;
    }

    const wasPlaying = !audio.paused;
    const previous = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
    pendingSeek.current = previous;
    setFailed(false);
    setBuffering(true);

    audio.src = src;
    audio.load();

    const onLoaded = () => {
      const target = pendingSeek.current ?? 0;
      const total = Number.isFinite(audio.duration) ? audio.duration : 0;
      if (total > 0) {
        audio.currentTime = Math.min(Math.max(0, target), Math.max(0, total - 0.05));
      }
      setDuration(total);
      setCurrentTime(audio.currentTime || 0);
      setBuffering(false);
      if (wasPlaying) {
        void audio.play().catch(() => setPlaying(false));
      }
      pendingSeek.current = null;
    };

    audio.addEventListener('loadedmetadata', onLoaded, { once: true });
    return () => audio.removeEventListener('loadedmetadata', onLoaded);
  }, [src]);

  // Element events.
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const onTime = () => setCurrentTime(audio.currentTime);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onWaiting = () => setBuffering(true);
    const onReady = () => setBuffering(false);
    const onError = () => {
      setFailed(true);
      setPlaying(false);
      setBuffering(false);
    };

    audio.addEventListener('timeupdate', onTime);
    audio.addEventListener('play', onPlay);
    audio.addEventListener('pause', onPause);
    audio.addEventListener('waiting', onWaiting);
    audio.addEventListener('playing', onReady);
    audio.addEventListener('canplay', onReady);
    audio.addEventListener('error', onError);

    return () => {
      audio.removeEventListener('timeupdate', onTime);
      audio.removeEventListener('play', onPlay);
      audio.removeEventListener('pause', onPause);
      audio.removeEventListener('waiting', onWaiting);
      audio.removeEventListener('playing', onReady);
      audio.removeEventListener('canplay', onReady);
      audio.removeEventListener('error', onError);
    };
  }, []);

  // Leaving the screen must never leave audio playing in the background.
  useEffect(() => {
    const audio = audioRef.current;
    return () => {
      audio?.pause();
    };
  }, []);

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || !src) return;
    if (audio.paused) {
      void audio.play().catch(() => setPlaying(false));
    } else {
      audio.pause();
    }
  }, [src]);

  const pause = useCallback(() => {
    audioRef.current?.pause();
  }, []);

  const seek = useCallback((seconds: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    const total = Number.isFinite(audio.duration) ? audio.duration : 0;
    if (total <= 0) return;
    audio.currentTime = Math.min(Math.max(0, seconds), Math.max(0, total - 0.05));
    setCurrentTime(audio.currentTime);
  }, []);

  return { audioRef, playing, buffering, failed, currentTime, duration, toggle, pause, seek };
}
