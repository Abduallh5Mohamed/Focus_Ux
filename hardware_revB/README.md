# FOCUS Rev B - small clip + phone gateway + optional GPU server

## Decision

Rev A was a wired bench rig, not walking eyewear. Do not carry the65x32mm Pico controller and its79mm pod forward onto the frame. Rev B explores a detachable sensor clip for existing eyeglasses. The frame shown is context only; retaining the user's own prescription eyewear avoids pretending a generic printed frame is an optical product.

Candidate prototype family: Seeed XIAO ESP32-S3 Sense with camera, digital microphone and2.4GHz WiFi. Manufacturer sheet lists21x17.8x15mm with expansion board. Camera revisions differ (OV2640/OV3660/OV5640 in manufacturer resources); the exact purchased revision, optical centre, height, mic port, antenna and USB geometry must be verified before detailed apertures/retention or purchasing final parts.

## What this revision actually delivers

- Native mechanical packaging study: mechanical/FOCUS_RevB_Clip_Packaging.FCStd, STEP and3 STL parts. Main review cradle24x18x21mm; complete printable clamp envelope36x41x21mm. These are CAD geometry sizes, not a tested wearable or a final PCB/package envelope.
- A manufacturer-sized reference box for the candidate module, not a fabricated internal electronics design.
- Native FreeCAD rendered previews, geometry validity report, no print-part/module-envelope intersection.
- This architecture decision and explicit verification gates.
- NO new KiCad wireless PCB, camera/antenna/charger circuit or streaming firmware is delivered. Rev A carrier does not implement this architecture. Those require exact module revision and an electrical/RF/thermal design review.

## Recommended first wireless topology

Camera+mic on glasses -> WiFi to Android phone in pocket -> Internet to GPU service -> processed audio to phone -> wired headset initially.

The MCU captures and packetizes synchronized media and handles controls; it does not run Dolphin. The phone is a native foreground-service gateway with screen-off/permission/network-transition behavior explicitly tested. A PWA is still useful for upload/controls, but background gateway reliability cannot simply be assumed from an installable web page.

The first radio bench test uses a local access point and local GPU host, avoiding cellular variability. Next test phone hotspot/local transport and upstream mobile-data routing. On Android, using local WiFi for glasses while routing server traffic over cellular needs deliberate networking implementation and device testing. Do not assume all phones bridge the two automatically for the app.

Returned audio is played by the phone, avoiding a second wireless audio stack/DAC/amplifier on the glasses. Test wired output before adding Bluetooth-headset latency/coexistence. Direct on-glasses playback is a separate design.

No standalone SIM/LTE module in the first wearable revision. It is a possible later product choice with different antenna, power peaks, thermal, data-plan and carrier/region requirements. WiFi is not cellular internet; the phone/AP supplies reachability.

## Cloud feasibility is not low-latency proof

End-to-end delay includes exposure/capture, media buffering, encode/packetization, uplink, server queue, model lookahead/inference, downlink, jitter buffer and audio output. Sending a2-second batch to a fast server still waits for that batch before processing. A faster connection does not remove model lookahead or preprocessing cost.

The current audio-visual model must have a sustained bounded-latency path before it is presented as conversation assistance. If several seconds of delay are required, the user experience is delayed replay, not immediate selective listening. No numerical clinical tolerance is assumed.

Measure simultaneous camera+mic+WiFi at useful mouth/face resolution and stable timestamps; successful camera-only HTTP streaming is insufficient. Raw mono16kHz16bit PCM is256kbit/s before overhead; video bitrate must be measured from actual encoder output and face visibility. Do not advertise cellular usage from radio PHY rates.

Use sequence numbers, capture timestamps, an explicit session/target ID and bounded buffers. Discard stale output after disconnect/target changes rather than playing old speech as current. Indicate degraded/disconnected state. Encrypted authenticated sessions and an active-capture indicator are part of the proposed implementation; no secret camera capture or default retained recording is assumed.

## Wearability scope

Rev B moves camera/control into a much smaller corner clip; it does not prove comfort. The full clamp is wider than the development board. Current CAD is an envelope study, with open optical/acoustic face and service lid because actual component locations are not yet measured. No guessed antenna clearance or claimed custom thin board is hidden inside.

For first trials, supply USB power from a pocket source; no unqualified LiPo/charger is placed next to the face. A later protected battery/power subsystem may move into a balanced temple pair or neckband after current, temperature, runtime and weight are measured. No battery-life/weight claims have been calculated. Cable strain relief, soft liners, sweat/skin compatibility, edge finishing and clamp torque remain open.

## Proof gates before final custom hardware

1. Real GPU selected-speaker extraction is verified against existing references on the computer.
2. Candidate module sample demonstrates concurrent A/V capture with adequate mouth pixels, frame cadence and synchronization.
3. Local WiFi end-to-end test runs continuously without growing buffers; report median/p95/max latency, dropped/late frames and per-target quality. Include walking/head movement/target loss in the test conditions.
4. Phone relay and remote server are tested under variable uplink, jitter, reconnection and locked-screen conditions. No claim of always-on outdoor service until verified.
5. Measure electrical current/peaks and surface temperatures; choose power source and antenna arrangement based on those data. Then physical fit/comfort/retention tests and revised CAD.
6. Only after the above, select exact BOM and create a reviewed customPCB/DFM release. The devkit's built-in camera/mic/WiFi is a prototype shortcut, not evidence that we designed the complete electronics.

## Primary sources
- Seeed manufacturer product sheet (dimensions, peripherals): https://files.seeedstudio.com/Bazaar/product_pdf/113991115.pdf
- Current Seeed getting-started and revision notes: https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/
- ESP32-S3 radio capabilities: https://www.espressif.com/products/socs/esp32-s3

## Open files
mechanical/FOCUS_RevB_Clip_Packaging.FCStd - FreeCAD native. Source-script driven geometry; edit generator dimensions and regenerate, not just decorative properties.
mechanical/FOCUS_RevB_Clip_Packaging.step - review exchange geometry.
mechanical/stl/ - fit-study parts, not released print orientations or approved wearable material.
