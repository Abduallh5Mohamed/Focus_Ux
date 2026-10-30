import { describe, expect, it } from 'vitest';

import { clamp, formatBytes, formatClock, formatDuration, formatTimestamp } from '../format';

describe('formatClock', () => {
  it('pads seconds', () => {
    expect(formatClock(0)).toBe('0:00');
    expect(formatClock(9)).toBe('0:09');
    expect(formatClock(75)).toBe('1:15');
  });

  it('is defensive about bad input', () => {
    expect(formatClock(Number.NaN)).toBe('0:00');
    expect(formatClock(-5)).toBe('0:00');
  });

  it('does not display a positive subsecond clip as zero', () => {
    expect(formatClock(0.16)).toBe('0:00.16');
    expect(formatClock(0.166667)).toBe('0:00.166');
    expect(formatClock(0.006)).toBe('0:00.006');
  });
});

describe('formatDuration', () => {
  it('renders arabic units', () => {
    expect(formatDuration(9_000)).toBe('9 ث');
    expect(formatDuration(65_000)).toBe('1 د 5 ث');
  });

  it('preserves a subsecond uploaded or extracted duration', () => {
    expect(formatDuration(160)).toBe('0.16 ث');
    expect(formatDuration(166.667)).toBe('0.167 ث');
    expect(formatDuration(0)).toBe('0 ث');
  });

  it('renders a dash when unknown', () => {
    expect(formatDuration(null)).toBe('—');
    expect(formatDuration(undefined)).toBe('—');
  });
});

describe('formatTimestamp', () => {
  it('converts ms to a clock', () => {
    expect(formatTimestamp(61_500)).toBe('1:01');
  });
});

describe('formatBytes', () => {
  it('scales the unit', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
  });
});

describe('clamp', () => {
  it('bounds the value', () => {
    expect(clamp(-1, 0, 1)).toBe(0);
    expect(clamp(2, 0, 1)).toBe(1);
    expect(clamp(0.4, 0, 1)).toBe(0.4);
  });
});
