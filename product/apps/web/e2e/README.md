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

Startup navigation regressions use a test-only Node HTTP receiver on an ephemeral
port, proxying Vite through the same origin. They do not intercept cleanup with
Playwright routing. Create is held across SPA route unmount and released only
after a replacement is recording and rendering marker audio. Both response-token
and original-request-token ownership are checked: only the abandoned ID is
cleaned up, with no extra camera request, recorder start or AudioContext, and the
replacement keeps uploading/polling and can stop normally.

Separate native document-navigation and tab-close cases leave camera permission
pending after Create identifies the session. Trusted browser `pagehide` events
and authenticated, empty-body Stop requests must reach the HTTP receiver even
while Stop replies are held beyond document destruction. A passive fetch observer
also checks the keepalive flag. These are controlled lifecycle regressions, not
real permission-prompt timing, process-crash recovery, or proof that cleanup can
identify a session when the browser disappears before Create returns. Existing
tests that manually dispatch `pagehide` are synthetic cancellation checks and
must not be described as native lifecycle evidence.

Finalization regressions hold an audio response until after final readiness
(or final failure), then hold native WAV decoding too. The report must wait for
both before metrics are fetched. HTTP failures, invalid WAVs, and the 10-second
fetch/body/decode deadline produce explicit null-audible rows, including declared
missing chunks; later decoded chunks are still scheduled exactly once. A response
arriving after the deadline must not start playback or change the final report.
If saving the complete report fails or exceeds its own 10-second deadline,
the final recording still opens with a visible metrics-not-saved warning;
metrics are not fetched and terminal polling does not retry forever.

This is a browser/network regression test, **not** evidence of real inference
quality, real-device latency, or the GPU/camera acceptance gate.
