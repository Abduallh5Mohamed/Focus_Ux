# WeSep in the website: research-only Windows trial

Status: **wired, not measured.** Nothing in this repository claims a real GPU result for WeSep.
The checkpoint licence is unresolved, so this is a research trial only, never a product setting.
By default (`FOCUS_OVERLAP_EXTRACTOR` unset) the website output is exactly the strict gated output.

## What the website does with it
- Every enrollment (picked voice, time range, uploaded voice file) provides clean reference audio for the
  target-conditioned model, or the result says why none exists ("skipped" with a reason). Uploaded voice files
  keep a short clean reference clip with the enrollment; it is deleted with the video's voice data.
- After enrollment, isolation uses audio only: no transcription, no face or lip data.
- The finished job has `result.routing`: extractor requested, whether it ran, overlap seconds, windows,
  pieces extracted/muted, fallback used and seconds, and `isolation_claim` (`strict_isolation` or
  `not_isolation`), plus one line per overlap piece. The result screen shows it in plain words and says
  "not isolation" whenever the original mix played quietly (continuity fallback).

## Step 1. Send the code to GitHub (from the Replit shell)
```
git status
git push origin HEAD
```
Never use `--force`. If the push is refused, stop and ask; do not force it.

## Step 2. Update the laptop checkout (PowerShell)
```
cd <your checkout folder>
git fetch origin
git pull --ff-only
```
If `--ff-only` fails, your copy has local changes or diverged. Stop; do not merge or reset to make it work.
Do not use the downloadable ZIP for this trial. It is only valid when it says it is complete; otherwise the
website refuses to build it and tells you to use the checkout.

## Step 3. Check the connection (loads no models)
Double-click `product\tools\Check-Connection.cmd`. It must report the server reachable and the key accepted.
Use the main app URL, not a task preview.

## Step 4. Run the validation (existing tool)
```
product\tools\Overlap-Validate.cmd target_enroll.wav two_speakers_5to10s.wav meeting_with_overlap.wav
```
It stops at the first failure. Send back the whole `validation-out` folder.

## Step 5. Research-only website trial (this window only)
Open a NEW Command Prompt window, then:
```
set FOCUS_OVERLAP_EXTRACTOR=wesep_bsrnn
product\tools\Start-Worker-Checkout.cmd
```
The variable exists only in that window. Closing the window ends the trial; the normal
`Start-Worker.cmd` in any other window is unchanged. Keep `FOCUS_ISOLATION_MODE` unset (strict) for the first run.
Then, on the website: upload a recording with overlapping speech, pick the person, confirm the voice, isolate.

## What to send back
- The `validation-out` folder (Step 4).
- A screenshot or copy of the note on the result screen.
- The job's routing summary (the same values the note shows).
- Whether you listened to the isolated audio and whether it is the right person.
- Never send keys, tokens or personal recordings you do not want shared.

## Pass criteria (all must hold)
1. The note says "extracted by WeSep" (`extractor_ran` is true).
2. Overlap seconds is above zero.
3. At least one extracted piece was kept (`pieces_extracted` > 0).
4. The result is not continuity-only (`fallback_used` is false, claim is `strict_isolation`).
5. On listening, the kept overlap is the target voice.

If any fails, the website milestone stays open. "Overlap muted" is a safe outcome, not a pass.
