import { describe, expect, it } from 'vitest';

import { K_AUDIO, K_FRAME, packBatch, unpackBatch } from '../lib/live/streamProto';

describe('stream wire format', () => {
  it('round-trips records with explicit positions', () => {
    const bytes = packBatch(7, [
      { kind: K_AUDIO, position: 32000, data: new Uint8Array([1, 2, 3, 4]) },
      { kind: K_FRAME, position: 1280, data: new Uint8Array([9]) },
    ]);
    const { seq, records } = unpackBatch(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length) as ArrayBuffer);
    expect(seq).toBe(7);
    expect(records.map((r) => [r.kind, r.position, [...r.data]])).toEqual([
      [K_AUDIO, 32000, [1, 2, 3, 4]],
      [K_FRAME, 1280, [9]],
    ]);
  });

  it('rejects truncated batches', () => {
    const bytes = packBatch(0, [{ kind: K_AUDIO, position: 0, data: new Uint8Array(8) }]);
    expect(() => unpackBatch(bytes.slice(0, bytes.length - 2).buffer)).toThrow();
  });
});
