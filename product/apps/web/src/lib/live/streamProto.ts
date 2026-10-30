/** Wire format shared with services/worker/stream_proto.py. */
export const K_AUDIO = 1;
export const K_FRAME = 2;
export const K_OUT_AUDIO = 3;
export const K_JSON = 4;
export const SAMPLE_RATE = 16000;

export interface StreamRecord {
  kind: number;
  position: number;
  data: Uint8Array;
}

const MAGIC = [0x46, 0x4c, 0x53, 0x31]; // "FLS1"

export function packBatch(batchSeq: number, records: StreamRecord[]): Uint8Array {
  const size = records.reduce((n, r) => n + 13 + r.data.length, 8);
  const out = new Uint8Array(size);
  const view = new DataView(out.buffer);
  out.set(MAGIC, 0);
  view.setUint32(4, batchSeq, true);
  let pos = 8;
  for (const r of records) {
    view.setUint8(pos, r.kind);
    view.setBigUint64(pos + 1, BigInt(Math.max(0, Math.round(r.position))), true);
    view.setUint32(pos + 9, r.data.length, true);
    out.set(r.data, pos + 13);
    pos += 13 + r.data.length;
  }
  return out;
}

export function unpackBatch(buffer: ArrayBuffer): { seq: number; records: StreamRecord[] } {
  const bytes = new Uint8Array(buffer);
  const view = new DataView(buffer);
  if (bytes.length < 8 || MAGIC.some((b, i) => bytes[i] !== b)) throw new Error('bad stream batch');
  const records: StreamRecord[] = [];
  let pos = 8;
  while (pos < bytes.length) {
    if (pos + 13 > bytes.length) throw new Error('truncated stream record');
    const length = view.getUint32(pos + 9, true);
    if (pos + 13 + length > bytes.length) throw new Error('truncated stream record');
    records.push({
      kind: view.getUint8(pos),
      position: Number(view.getBigUint64(pos + 1, true)),
      data: bytes.slice(pos + 13, pos + 13 + length),
    });
    pos += 13 + length;
  }
  return { seq: view.getUint32(4, true), records };
}
