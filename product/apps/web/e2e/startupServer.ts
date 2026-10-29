import { createServer, request as httpRequest, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { markerWav } from './audioProbe';

/** Test-only API receiver. Unlike page.route, it survives destruction of a document.
 * Proxy Vite through the same origin so cleanup uses ordinary same-origin HTTP. */
export async function startupServer() {
  const requests: { path: string; method: string; authorization?: string; bytes: number }[] = [];
  const evidence: { event: string; trusted?: boolean; keepalive?: boolean }[] = [];
  const creates: ServerResponse[] = [];
  const uploaded = new Set<string>();
  const stopped = new Set<string>();
  const pendingStops: ServerResponse[] = [];
  let holdStops = false;
  const view = (id: string) => ({
    live_session_id: id, phase: stopped.has(id) ? 'finalizing' : 'live',
    mode: 'live', target_face_id: 'face', queue_depth: 0,
    chunks: uploaded.has(id) ? [{
      seq: 0, state: 'ready', capture_start_ms: 0, duration_ms: 300, error: null, warnings: [],
    }] : [],
    final: { status: null }, error: null,
  });
  const json = (response: ServerResponse, body: unknown) => {
    response.writeHead(200, { 'Content-Type': 'application/json' });
    response.end(JSON.stringify(body));
  };
  const server = createServer((request, response) => {
    const path = new URL(request.url!, 'http://test').pathname;
    if (path.startsWith('/api/') || path === '/__lifecycle') {
      const buffers: Buffer[] = [];
      request.on('data', (buffer: Buffer) => buffers.push(buffer));
      request.on('end', () => {
        const body = Buffer.concat(buffers);
        if (path === '/__lifecycle') {
          evidence.push(JSON.parse(body.toString()));
          response.writeHead(204).end();
          return;
        }
        requests.push({ path, method: request.method!, authorization: request.headers.authorization,
          bytes: body.length });
        if (path === '/api/live/sessions' && request.method === 'POST') {
          creates.push(response); // Explicitly released by the test, never by a timer.
          return;
        }
        const match = path.match(/^\/api\/live\/sessions\/([^/]+)(.*)$/);
        if (!match) {
          response.writeHead(404).end();
          return;
        }
        const [, id, action] = match;
        if (action === '/stop') {
          stopped.add(id);
          if (holdStops) pendingStops.push(response);
          else json(response, view(id));
        } else if (/^\/chunks\/\d+\/audio$/.test(action)) {
          response.writeHead(200, { 'Content-Type': 'audio/wav' });
          response.end(markerWav(2));
        } else if (/^\/chunks\/\d+$/.test(action) && request.method === 'PUT') {
          uploaded.add(id);
          json(response, { state: 'received', duplicate: false });
        } else if (!action && request.method === 'GET') {
          json(response, view(id));
        } else {
          response.writeHead(404).end();
        }
      });
      return;
    }
    const upstream = httpRequest({
      hostname: '127.0.0.1', port: 5173, path: request.url, method: request.method,
      headers: { ...request.headers, host: '127.0.0.1:5173' },
    }, (result) => {
      response.writeHead(result.statusCode!, result.headers);
      result.pipe(response);
    });
    upstream.on('error', () => response.writeHead(502).end());
    request.pipe(upstream);
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  return {
    origin: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
    requests, evidence, creates,
    releaseCreate(index: number, id: string, token?: string) {
      json(creates[index], { live_session_id: id, session_token: token, chunk_ms: 300, max_chunks: 100 });
    },
    holdStops() { holdStops = true; },
    releaseStops() {
      for (const response of pendingStops.splice(0)) json(response, {});
    },
    async close() {
      server.closeAllConnections();
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    },
  };
}
