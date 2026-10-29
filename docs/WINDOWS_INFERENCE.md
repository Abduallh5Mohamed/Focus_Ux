# Windows GPU inference connection

For an entirely local Windows trial (UI + isolated API + existing GPU worker),
use [LOCAL_WINDOWS_TRIAL.md](LOCAL_WINDOWS_TRIAL.md). The instructions below
describe the separate Replit-connected setup, not the all-local launcher.

## Status and external blockers

The user confirmed the old application isolated audio on their Windows computer
and agreed to keep that computer on for inference. Screenshots locate the old
installation at `A:\focus` and a Dolphin cache directory under
`A:\focus\cache\hf\hub`. A directory name does **not** verify complete weights.

This Replit workspace has no model weights, mean-face asset or CUDA runtime.
The real adapter is now connected through selectable local/remote providers.
The operator saved the worker credential through the secure form, remote mode
was enabled, and a Windows screenshot shows “Models loaded”. The screenshot
then shows repeated connection failures, and the server has not observed a
successful worker poll. The updated no-GPU connection check confirmed a redirect
before reaching FOCUS from Windows. Comparing the operator's Networking page
with the task environment then established that these were **different preview
hosts**: the main app had no worker routes yet (404), while the task app had the
new protected routes (401 without worker credentials). The operator clarified
that Private preview had just been disabled for the explicitly approved temporary
test; the screenshot is not evidence of its earlier state. The operator then
re-ran Check-Connection against the task host and still received the redirect.
Do not interpret that task-host redirect as proof that the main preview needs
further privacy changes.

Model loading is evidence only for initialization. The remaining prerequisite
is merging this implementation, restarting the main application, and checking
the worker against the main URL shown in Networking, not repeating the blocked
isolated task-host connection. Success on the main host is not yet established.
**No real upload → faces → selected speaker → isolated audio run is verified.**

Remaining requirements for that test:

1. Merge this implementation into the main app and restart its workflow. Confirm
   the main environment has `FOCUS_INFERENCE_MODE=remote` and the existing worker
   secret (check existence only, never print it). No new packages are required.
2. Use the **main** URL shown in Networking with `Check-Connection.cmd` before
   loading models again. Reuse the existing saved worker key; no setup reset.
3. Only if that main URL is private and redirects to sign-in, provision a **Development** external
   access token via Replit's access controls. Save it on Windows using
   `Setup-Preview-Access.cmd`'s hidden prompt, never in a URL/chat/screenshot.
   Do not publish the app as a workaround. A temporary public-preview test
   requires explicit informed consent and must be closed afterwards.
   Official documentation says token controls appear only after a first
   publication with deployment access set to Private. Check whether controls
   already exist; if not, this is an external setup blocker under the current
   no-publication constraints. Do not ask the operator to publish this task fork.
4. Original Python environment initializes and successfully polls the API.
5. A real multi-speaker clip is uploaded, a non-first face is selected, and the
   returned protected WAV is listened to for identity, quality and alignment.
   Check another session cannot fetch its video, thumbnails or isolated audio.

## Simple operator setup

1. After merge, download `/api/worker-kit.zip` from the **main app preview**. This is source
   code, not a model download. Extract to a new folder, not over `A:\focus`.
2. Double-click `Setup-Key.cmd`. It uses the existing Python environment and
   creates a random private key in `%LOCALAPPDATA%\FocusWorker\worker-token`.
   It copies that key to the clipboard without printing it.
3. Paste it **only** into Replit Secrets as `FOCUS_WORKER_TOKEN`. Do not send it
   in chat, a screenshot or a URL. Clear the clipboard after saving.
4. Set non-secret `FOCUS_INFERENCE_MODE=remote`, then restart Start application.
5. Double-click `Start-Worker.cmd`. Paste the main URL from Networking, **not an
   isolated task's preview URL**.
   Both the site root and an address ending in `/api` are accepted.
6. Wait for “Models loaded. Connecting to the website...” and keep the window
   open. If original assets/dependencies are missing, startup fails honestly.
7. Upload a short real clip (up to 15 seconds / 50 MB), wait for faces, select
   the desired person, and play the isolated audio. Report non-secret error text
   if the original environment cannot initialize. Do not send personal footage.

If setup has already succeeded, do **not** repeat key generation on restart.
Run `Check-Connection.cmd` first if connection is uncertain. It performs an
authenticated handshake without loading GPU models, claiming work or marking
the worker connected. `Start-Worker.cmd` now performs this check automatically
before initialization. Connection/setup failures stop with a specific message,
not a repeated generic model error.

The script does not install packages, modify original source/weights, train
models, open a listening port or configure a tunnel. Existing library caches
may write their own cache metadata. Model network connections are blocked during
inference so missing auxiliary weights cannot trigger an automatic download.

## Privacy and trust boundary

The worker credential trusts the operator's computer to process **all queued
users' media on this application**, not just the operator's browser session.
Use only a trusted computer and only for the agreed application. Browser tokens
cannot call worker endpoints; the worker token cannot call browser media
endpoints. Neither credential is placed in URLs or the downloaded source kit.

A private Replit development URL may require a **separate** platform access
credential for non-browser requests, even when the signed-in browser works.
The optional development access token uses `Authorization`; application-level
worker auth uses `X-Focus-Worker-Token`. Legacy direct requests can still use the
worker key in `Authorization` when no platform gate is present. A platform
credential alone never authorizes worker tasks. Redirects remain refused; no
automatic credential forwarding is permitted.

The official development-URL page explicitly gates the token UI on a prior
private publication. A successful server-side request does not establish that
the operator's external Windows client can reach the same URL. Check available
controls before promising that an access token can be created without publishing.

Official guidance: https://docs.replit.com/core-concepts/project-editor/app-setup/development-urls
and https://docs.replit.com/features/deployment-customization/external-access-tokens
and https://docs.replit.com/learn/build-in-parallel

Each worker task grants access only to its current canonical video. Its random
ID is revoked on completion, timeout, deletion or shutdown. No media enumeration,
arbitrary remote paths or output filenames are accepted. A SHA-256 digest checks
that downloaded media matches the offered canonical bytes. HTTP redirects are
refused to avoid sending the worker credential to a different destination.

Media/audio on Windows live in per-task temporary directories removed after
success or error. An abrupt OS crash may leave files in Windows TEMP; remove
abandoned `focus-inference-*` folders there. Model assets remain local.

To revoke access, remove or rotate `FOCUS_WORKER_TOKEN` and restart the server.
Close the Windows worker. Set `FOCUS_INFERENCE_MODE=unavailable` when not using
remote inference. Never commit the key file. Each Windows account allows only
one active worker process. Tasks are not automatically replayed after expiry.

## Identity, media and limitations

- Server-side ffmpeg creates an orientation-corrected 25 fps MP4. Canonical
  dimensions are persisted; duration must remain within 80 ms of the upload.
- Detection thumbnails, face identity, selection, extraction and browser video
  all refer to that same canonical video. The true API video ID is always sent,
  never a filename-derived identity. Detector result ordering is not selection.
- First-frame faces only; no voice-only or later-appearing target support.
- Worker output must be a complete mono PCM16 WAV at 16 kHz, aligned within
  80 ms of canonical video duration. Offset is zero. Invalid/truncated or shifted
  output is rejected, and no fake fallback is available.
- One serialized dispatcher and at most one outstanding remote task per server.
  Run a single API process. Remote work is transient: a server restart fails
  interrupted work through existing dispatcher recovery, not replay/re-lease.
- A 15-minute timeout fails work explicitly. The computer finishes/cleans its
  own current task before polling again; expired outputs are rejected.
- No transcript model is connected here; audio and transcript statuses remain
  independent.
- Preview addresses can change. Restart the Windows worker with the current
  trusted HTTPS address if that happens. This is not a public deployment.

## Executed verification versus real inference

`product/tests/inference` exercises worker authorization, bounded results,
timeout/deletion/replay rejection, second-face identity transport, WAV validation,
download-kit allowlisting, no-download failure and actual ffmpeg normalization.
Its detector and audio responses are explicitly synthetic fixtures. Existing ML
and worker unit suites likewise do not establish that the user's GPU works.
The real Windows initialization and listening test above remain external blockers.
