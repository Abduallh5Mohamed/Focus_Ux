# Live playback browser regression

Run from `product/apps/web`:

```sh
npm ci
npx playwright install chromium
npm run test:browser
```

For environments with a preinstalled Chromium, set
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to its executable instead of downloading
a browser. The tests start their own frontend on port 5173 with live mode
enabled; they do not change the normal preview's opt-in flags or start a backend.
Traces on failure go to the ignored root `generated-artifacts/playwright/`.

The integration test uses real Chromium camera/microphone test devices,
MediaRecorder, HTTP requests, AudioContext clock, WAV decoding and source nodes.
Only API responses are simulated: chunk audio arrives out of order, one response
is late, and an upload is held until explicitly released with an error.
Small PCM marker WAVs let an output probe distinguish each rendered chunk.
Assertions cover output order, no duplicate playback, continuous recovered
chunks (at most one 128-frame render quantum at a resampled boundary), continued
polling during the stalled upload, camera release while stopping, and visible
late/upload-failure/missing states. A second test delays a native decode result
and checks ordering and close-during-decode.

This is a browser/network regression test, **not** evidence of real inference
quality, real-device latency, or the GPU/camera acceptance gate.
