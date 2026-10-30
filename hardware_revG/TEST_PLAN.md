# FOCUS RevG — verification plan and empty result register

Date2026-10-30. All rows `NOT RUN` unless explicitly linked to an archived CAD/EDA result; those do not count as physical tests. User acceptance targets: two hours full continuous; four hours typical with defined profile; <=60g worn target, 70g exceptional upper limit; capture-to-bone p95<=150ms, >200ms not described as live; two Egyptian mobile operators; engineering batch10–20 before100 pilot.

| ID | Procedure / instrument | Acceptance before engineering unit design freeze | Actual result | Evidence |
|---|---|---|---|---|
| T01 | Four mic raw synchronous capture, logic analyzer + known sound source | Four distinct channels, correct map, common clock, measured skew/phase and no silent mix | NOT RUN | — |
| T02 | Camera+4mics+modem+DAC simultaneous on chosen host, 30min+ | No dropped stream, repeatable startup, bounded buffers, logs each clock domain | NOT RUN | — |
| T03 | Unplug/reset camera/modem/hub and recover | No stale audio, safe mute, no unrecoverable hung USB enumeration | NOT RUN | — |
| T04 | Real two-operator LTE trials, strong/weak coverage, walking | Capture-to-bone p50/p95/p99 reported each condition, p95<=150ms for live claim; >200ms fail live gate | NOT RUN | — |
| T05 | Server fault/reconnect/packet loss/jitter | Bounded backlog, stale generation muted, target identity not silently changed | NOT RUN | — |
| T06 | Target selection with overlapping people, target silent/offscreen/occluded | Correct face-to-audio binding verified blind, uncertain state on ambiguity; quality threshold defined before test | NOT RUN | — |
| T07 | Full2h continuous load profile, current logger and temperature logger | Runs >=2h with full function, no overtemperature, safe low-voltage shutdown | NOT RUN | — |
| T08 | Defined4h typical duty cycle and idle profile | Runs >=4h for recorded profile; active/idle currents and energy measured | NOT RUN | — |
| T09 | LTE transmit burst at low battery, scope at modem pins, battery/PCM/connector current | No voltage violation/reset; all components within supplier continuous/pulse and temperature limits | NOT RUN | — |
| T10 | Charger default/reset/NTC absent/open/short, current and voltage | No unsafe default charge; correct inhibit, fault indication and recovery on exact cell | NOT RUN | — |
| T11 | Amplifier dummy load, differential probe, DAC full-scale/fault/startup | Independently enforced electrical output cap and default hardware mute; no BTL short to ground | NOT RUN | — |
| T12 | Bone transducer impedance/force/contact, calibrated lab setup | Actual part identity, pressure range and limited output signed off by qualified audio specialist before worn audio | NOT RUN | — |
| T13 | Acoustic/vibration feedback capture across volume levels | No uncontrolled positive feedback; document noise/leakage/intelligibility | NOT RUN | — |
| T14 | Full assembly scale and CG with actual battery/parts/lenses | <=60g target; 60–70g requires documented justification and wear trial; >70g fails | NOT RUN | — |
| T15 | Mechanical static, fold sweep with wires, 1000+ early hinge cycles | No collisions, wire pinch, fatigue or contact-position drift; test selected hinge, not conceptual pivot | NOT RUN | — |
| T16 | RF VNA/OTA on complete head-worn assembly with both operators | Bands covered, tuned matching, stable attach and throughput; relevant head-worn compliance path documented | NOT RUN | — |
| T17 | Human fit, pressure, heat and removal trial with consent | No unacceptable discomfort in measured sample; no medical benefit claim from fit alone | NOT RUN | — |
| T18 | Privacy/status controls: capture LED, physical mute, stop/delete | Indicators correlate with actual camera/mic state; mute independent of software freeze | NOT RUN | — |
| T19 | Clean flash/reproducible firmware, diagnostic and factory test points | Identified SKUs/revisions, functional logs, repeatable unit screening | NOT RUN | — |

Archived design-screening only: RevA control carrier ERC/DRC passed; C/D fold screens failed; RevE static checks passed but no folding; RevG first-pass CAD currently records candidate folding failures and >70g partial estimated mass. The RevG electronics partial review schematic has unresolved pin/provisioning errors and no verified routed integrated PCB. See per-subsystem reports; no row above inherits a PASS from virtual geometry.

For latency, record source stimulus and bone-output vibration/electrical proxy on a single calibrated multichannel capture clock. Time-stamp camera exposure, each mic DMA block, uplink send/receive, server queue/model, downlink, playback buffer and transducer drive. Repeated real-network trials must include loss/outage; do not derive capture-to-ear from unsynchronized server timestamps.
