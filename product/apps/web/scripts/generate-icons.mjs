/*
 * Generates the local PWA icons so the manifest never depends on a CDN.
 * Zero dependencies: raw PNG encoding via node:zlib.
 *
 * Run: npm run icons
 */
import { deflateSync } from 'node:zlib';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const outDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'icons');

const BG = [11, 16, 22];
const RING = [34, 211, 238];
const GLOW = [14, 116, 144];

const crcTable = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c;
  }
  return table;
})();

function crc32(buf) {
  let c = -1;
  for (let i = 0; i < buf.length; i += 1) c = crcTable[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ -1) >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const typeBuf = Buffer.from(type, 'ascii');
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([len, typeBuf, data, crc]);
}

function encodePng(size, rgba) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // RGBA
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;

  const stride = size * 4;
  const raw = Buffer.alloc((stride + 1) * size);
  for (let y = 0; y < size; y += 1) {
    raw[y * (stride + 1)] = 0; // filter: none
    rgba.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride);
  }

  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

/** Anti-aliased coverage of a signed-distance style test, sampled 2x2. */
function coverage(px, py, inside) {
  let hits = 0;
  for (const dx of [0.25, 0.75]) {
    for (const dy of [0.25, 0.75]) if (inside(px + dx, py + dy)) hits += 1;
  }
  return hits / 4;
}

function blend(dst, offset, color, alpha) {
  if (alpha <= 0) return;
  const a = Math.min(1, alpha);
  dst[offset] = Math.round(dst[offset] * (1 - a) + color[0] * a);
  dst[offset + 1] = Math.round(dst[offset + 1] * (1 - a) + color[1] * a);
  dst[offset + 2] = Math.round(dst[offset + 2] * (1 - a) + color[2] * a);
  dst[offset + 3] = Math.max(dst[offset + 3], Math.round(255 * a));
}

function renderIcon(size, { padding = 0 } = {}) {
  const buf = Buffer.alloc(size * size * 4, 0);
  const c = size / 2;
  const inner = size - padding * 2;
  const outerR = inner * 0.34;
  const ringW = Math.max(2, inner * 0.055);
  const bracket = inner * 0.46;
  const bracketW = Math.max(2, inner * 0.05);

  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const o = (y * size + x) * 4;
      const px = x + 0.5;
      const py = y + 0.5;

      // Rounded-square plate (only when we are not a maskable icon).
      if (padding === 0) {
        const r = size * 0.22;
        const dx = Math.max(Math.abs(px - c) - (c - r), 0);
        const dy = Math.max(Math.abs(py - c) - (c - r), 0);
        const dist = Math.hypot(dx, dy);
        const cov = 1 - Math.min(1, Math.max(0, (dist - r) / 1.5));
        blend(buf, o, BG, cov);
      } else {
        blend(buf, o, BG, 1);
      }

      const d = Math.hypot(px - c, py - c);

      // Soft glow inside the ring.
      if (d < outerR) blend(buf, o, GLOW, 0.16 * (1 - d / outerR));

      // Main ring.
      const ringCov = 1 - Math.min(1, Math.abs(d - outerR) / (ringW / 2));
      blend(buf, o, RING, ringCov);

      // Four corner brackets: the "focus" frame.
      const bx = Math.abs(px - c);
      const by = Math.abs(py - c);
      const onArmX = bx > bracket - bracketW && bx <= bracket;
      const onArmY = by > bracket - bracketW && by <= bracket;
      if ((onArmX && by <= bracket) || (onArmY && bx <= bracket)) {
        const covX = coverage(px, py, () => true);
        blend(buf, o, RING, 0.55 * covX);
      }

      // Centre dot.
      if (d < inner * 0.055) blend(buf, o, RING, 0.9);
    }
  }
  return encodePng(size, buf);
}

mkdirSync(outDir, { recursive: true });
writeFileSync(join(outDir, 'icon-192.png'), renderIcon(192));
writeFileSync(join(outDir, 'icon-512.png'), renderIcon(512));
writeFileSync(join(outDir, 'icon-maskable-512.png'), renderIcon(512, { padding: 64 }));
writeFileSync(join(outDir, 'favicon.png'), renderIcon(64));

console.log('icons written to', outDir);
