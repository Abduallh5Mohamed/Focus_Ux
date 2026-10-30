# FOCUS glasses — consolidated hardware engineering review dossier

Prepared: 2026-10-30. Purpose: independent feasibility/design review, not a manufacturing release or purchase order.

## Executive status / اقرأ هذا أولًا

المطلوب نظارة مستقلة ببطارية وشريحة Nano-SIM خاصة بها، تلتقط البيئة وتسمح باختيار شخص وسماع صوته عبر التوصيل العظمي. لا يعتمد المنتج النهائي على إنترنت هاتف في الجيب. معالجة العزل الحالية خارج النظارة. لم يتم بناء أو تشغيل نظارة مادية ضمن الأدلة المتاحة.

الحزمة تجمع كل الملفات الهندسية الموجودة من RevA إلى RevF. **أحدث CAD موجود هو RevE، وهو دراسة USB لا تستوعب النظام الخلوي الكامل. أحدث دراسة كهرباء وطاقة واتصال هي RevF، لكنها ليست PCB أو تجميع CAD مكتملًا.** ملفات تصنيع RevA تخص لوحة أزرار Pico فقط، وليست إلكترونيات النظارة النهائية. لا تجمع قوائم القطع من كل الأجيال كأنها منتج واحد.

Please review the original native files alongside this summary. Published component figures below are transcribed from the existing project source documents, principally checked on 2026-10-29. Availability, exact variants and current documentation were not independently revalidated during packaging. Treat candidates and unresolved selections accordingly.

## 1. Intended product and present technical boundary

- Wearable glasses; user selects an actual visible person, and hears that person's speech while others overlap.
- Live continuous audio, no mandatory isolated enrollment ritual. Face-to-voice association remains a software research/integration issue; voice timbre alone cannot identify a visible face.
- Bone-conduction output with adjustable, electrically insulated contact mounts. No prescription lenses or optical qualification delivered.
- Dedicated physical Nano-SIM, onboard LTE modem/antenna, rechargeable onboard pack. Phone may be a lab aid, not the product network gateway.
- Current proposed standalone data path: camera/microphone -> acquisition/transport host -> LTE uplink -> external inference -> returned audio -> codec/limited amplifier -> two bone transducers.
- No model has been frozen as meeting the required real-time quality. Dolphin's measured separation/latency has failed the intended use; later audio-only alternatives are proposals, not verified hardware features. Expert should challenge whether cellular/cloud latency is viable at all and whether local inference changes the processor/power choice.
- No optical display, eye tracking, microphone array, certified hearing-aid function, completed LTE firmware or custom integrated mainboard exists in this package.

## 2. Revision inventory and what each actually means

| Revision | Architecture/artifacts | Evidence boundary |
|---|---|---|
| A | USB camera/mic, external GPU/headset; Pico H button carrier; native KiCad + FreeCAD + STEP/STL + Gerbers | Control-only PCB; bulky wired packaging; virtual checks, no powered build |
| B | XIAO ESP32-S3 Sense clip for existing eyewear; Wi-Fi/phone-gateway concept | Smaller packaging study, no new wireless PCB or firmware; phone architecture later superseded |
| C | XIAO manufacturer STEP integrated into frame | CAD fit study; sampled hinge motion failed |
| D | XIAO front capture + two larger Adafruit bone exciters; external DAC/amp and wired return | Audio engineering proposal; static fit passes but folding tests fail |
| E | Arducam long brow camera/mic + miniature BS08 exciters, slim frame | Latest native CAD; external USB host/power/audio, no LTE/battery packaging; hinge/comfort unvalidated |
| F | Proposed standalone LTE power/RF architecture | POWER_AND_RF.md and references only; no finished main schematic, PCB, integrated CAD or firmware |

Keep D as historical bench reference and E as external-form direction. Neither mechanically implements F. Old phone-path diagrams are historical, not the current product requirement.

## 3. Candidate standalone architecture — RevF

```text
Camera/mic (B0441 USB candidate)
             |
       acquisition host (ESP32-P4 candidate; not qualified)
             | USB host/hub topology must be proven
       LTE modem A7670E + Nano-SIM + antenna
             |
       external inference server
             |
       returned encoded audio / bounded playback buffer
             |
       codec/DAC + muted, output-limited amplifier (TBD)
             |
       left/right BS08 transducers (two floating pairs if BTL)

Protected 1S pack <-> charger/power path -> modem/digital/camera/audio rails
```

ESP32-P4, USB2512B hub and a P4 ECO3-or-later preference were discussed as integration candidates. No matching final schematic, pin map, qualified silicon revision, USB bandwidth/driver evidence or full host stack was found in the current RevF folder. They remain **unfrozen**, not approved purchases. USB camera and USB modem simultaneous enumeration/transfer, audio capture and returned playback must be demonstrated together. Modem USB does not supply its VBAT. A SIM card is not a modem or compute host.

Processor choice is a major expert decision: validate P4-host feasibility versus a small Linux SoM with mature USB/camera/cellular/audio stack and its larger power/size budget. Do not promise tiny all-day glasses from chip dimensions alone.

## 4. Proposed standalone component details

All quantities in BOM_RevF_candidates.csv describe one conceptual glasses unit; unselected circuitry may need multiple ICs/passives/rails. This is NOT an orderable complete BOM.

### Capture and host

- Arducam B0441 USB2 UVC camera + single microphone: source table envelope 62 x 9 x 6 mm; MJPEG/UVC candidate in central brow. Included manufacturer-authored PDF via distributor. Actual USB audio class compatibility, modes/current, connector, microphone aperture, lens axis/FoV and A/V clock drift must be checked on a sample. No proven multi-mic directional capture.
- ESP32-P4: proposed acquisition/transport controller, not demonstrated local AI inference. Exact variant, PSRAM/flash, peripheral pins and multiple power rails/sequencing are TBD. Do not copy an ESP32-S3 pin map.
- Microchip USB2512B: proposed USB hub candidate only, to be reviewed for host topology, clocks, power switching, controlled impedance, driver support and actual camera/modem compatibility. No approved hub design exists here.

### Cellular, SIM and antenna

- SIMCom A7670E proposed baseline: 24 x 24 x 2.3 mm bare module, published supply 3.4–4.2 V, typical 3.8 V. Older hardware design requires >=2 A supply capability for maximum GSM transmit bursts; not an average LTE-current measurement. Confirm actual hardware/firmware revision, regional bands, operator/APN and modem USB descriptors/driver.
- GCT SIM8051-6-0-14-00-A Nano-SIM socket: six contacts, push-pull, 1.35 mm profile; no card-detect switch. Exact footprint and insertion travel must follow included drawing. 16 x 15 x 3 mm plus card travel is a provisional layout allowance, NOT a verified body dimension.
- Taoglas FXP40.07.0085A antenna: listed flex 42.6 x 12.1 x 0.15 mm, 85 mm coax, MHF-I/U.FL-compatible end. PDF headline 700–960 / 1710–2200 MHz does not establish all A7670E bands including B7. Website/PDF frequency discrepancy is unresolved. Confirm actual operator bands and antenna revision or replace it. Keep antenna away from cell foil, ground/shield, switching power and head loading; need RF tuning in the complete assembly.
- Quectel EG915U is an ALTERNATIVE, not a second installed modem: 23.6 x 19.9 x 2.4 mm, 3.3–4.3 V, typical 3.8 V, reviewed design supply 2.5 A. Variant/driver/bands require separate qualification. A7672 was another early candidate, not the selected baseline.

### Battery, power and charger

- Tattu TAA5001S95JSL / TA-95C-500-1S1P-L-JST: proposed standard 4.2 V-charge 1S LiPo, 500 mAh, nominal 3.7 V, 58 x 18 x 8 mm, 14 g, 1.85 Wh arithmetic energy. 95C label does not qualify final connector/wiring/PCM or authorize a particular operating current. Built-in protection not established. Need protected-pack supplier drawing and current/temperature/charge specification.
- BatterySpace PCB-S1A6TH / product5080 protection candidate: 33 x 5 x 2 mm, 0.45 g, listed 5 A continuous, overcurrent 7–9 A, <=40 milliohm. NTC is for external monitoring, not automatic thermal disconnect. Emergency cutoff is not normal system shutdown. Supplier must qualify complete pack/interconnect.
- Preliminary compartment allowance 65 x 22 x 12 mm includes protection/wire/insulation space; it is not drawn into RevE and is not a manufacturer assembled-pack size.
- TI BQ25895 charger/NVDC power path candidate, 4 x 4 mm IC: establish safe cell-specific current, charge voltage, termination and NTC limits. Published default charge current 2.048 A is unsuitable as an assumed setting for this small cell. Hold active-low CE high until safe settings and reset/watchdog/fault behavior are verified. No charging while worn for initial prototype.
- TI TPS55288 modem buck-boost candidate, 4.0 x 3.5 mm IC package, adjustable 3.8 V output. External inductor, capacitors, thermal, compensation and full solution area TBD. Switch-current headline is not output-current rating.
- Separate 3.3 V buck-boost/reference host rails, regulated 5 V USB VBUS boost, current limits, rail load switches, codec supply, ESD, input protection and USB-C CC circuitry are NOT selected/routed.

Power tree: USB-C -> input protection/current advertisement -> BQ25895 -> protected1S/BAT-SYS -> regulated3.8V modem + digital rails + 5V camera/hub + audio rails. No backfeeding of external USB.

Sizing example only: at 3.0 V battery/85% assumed efficiency, 3.8 V x 2 A modem demand draws about 2.98 A from the cell BEFORE host/camera/audio. This is a transient sizing illustration, not a measured load. Combined load may exceed the proposed 5 A PCM and requires complete redesign if so.

Runtime is unmeasured. Using an illustrative 1.30 Wh usable energy: 2 W ->39 min; 4 W ->19.5 min; 6 W ->13 min. These are scenarios, not predicted consumption or battery-life claims. No final total mass, centre of gravity, thermal map or battery lifetime is established.

### Bone-conduction playback

- RevE candidate: two BS08 (Shenzhen Hearing Technology catalog), each 13 x 7.4 x 5.6 mm, 1.7 +/-0.1 g, 8 ohm nominal, listed 0.8 W. Manufacturer catalog only; controlled drawing, purchased sample, active face, terminals and measured impedance remain open. Pair bare mass 3.4 g excludes mounts/wires. Catalog power/SPL is not a listening-level target.
- Final onboard codec/DAC/amplifier and hardware limiter/mute are **TBD**. No finalized BS08 circuit or firmware delivered. Old Adafruit987 settings must not be assumed valid for BS08.
- Historical D bench: Adafruit1674 exciters, 21.5 x 14 x 7.9 mm, 9.6 g each, product page 8 ohm/1 W nominal/2 W max. Linked C2049 PDF conflicts on impedance/power; included to expose the discrepancy, not resolve it by guessing.
- Historical D amplifier: Adafruit987 MAX98306 stereo breakout, 28.1 x 24 x 10.4 mm, 4.6 g; supply 2.7–5.5 V. Proposed low-output bench setting external current-limited3.0V, lowest9dB gain, attenuation/volume/mute. External USB DAC not selected. No assembled or calibrated result.
- BTL outputs: each exciter gets its own floating +/- pair; output-minus is NOT ground. No common-ground 3-wire headset cable, joined negative outputs or GPIO exciter drive. Validate initially on differential-measured dummy loads; audio power ratings are component limits, not verified human exposure.
- Need compliant adjustable contact mount, insulated terminals, strain relief, measured force, vibration transfer and feedback-to-microphone testing. Neither CAD nor bone conduction establishes clinical benefit.

## 5. Actual mechanical CAD — RevE

- Native FreeCAD: hardware_revE/mechanical/FOCUS_RevE_Wearability_Study.FCStd.
- STEP: matching .step; previews rendered from CAD, not photos of a built device.
- Ten modeled parts valid single solids; static intersections and reference component envelope overlaps passed at recorded pose. Source-sized simplified envelopes, not detailed internal manufacturer models.
- Nominal contact-cap inner span129mm; nominal fore/aft carrier adjustment +/-3mm. One study size, no population fit validation. Mechanical solid volume16.8cm3 is not measured finished weight.
- Camera full62x9x6 envelope with nominal0.4mm pocket allowance. Lens aperture is provisional registration, not controlled optical datum.
- Selected hinges, pressure mechanism, in/out fit, sealing, cable/flex routing, skin material, real lens retention and tolerances unresolved. Folding untested in E. E deliberately has no manufacturing STLs.
- E does NOT contain the cellular modem, battery, host, hub, charger or final amplifier. Adding an SIM-looking slot does not implement standalone operation. Major repackaging and likely thickness/weight tradeoff required.
- Historical C/D folding screening FAILED with positive-volume clashes. Preserve reports; static fit does not override dynamic failure.

## 6. Actual electronics CAD — RevA only

Native KiCad10.0.7 project, schematic, routed PCB, PDFs, netlist, local symbols and Gerber/drill included under hardware_revA/electronics.

- Two-layer FR4 carrier65x32x1.6mm for Raspberry Pi Pico H SC0917. No camera/audio/USB data routing, LTE, charger or power conversion on this PCB.
- GP2 physical4 -> SELECT_N dry contact; GP3 physical5 -> STOP_N; internal pullups. GP4 physical6 ->1kohm ->greenLED; physical3GND. Inputs are internal dry contacts only.
- J1/J2 two1x20 female2.54mm sockets; J3/J4 two1x2 headers; two external NO switches. Candidate Samtec SSW-120-01-G-S and Kingbright WP3A8GD; unresolved entries remain unresolved.
- Four2.4mm NPTH at (3,3),(62,3),(3,29),(62,29)mm. Nominal0.3mm tracks; no high-speed controlled-impedance requirement for this control-only design.
- Archived checks: ERC0 errors/0warnings; DRC0violations/unconnected; parity0; five connected nets matched;40/40 module-pad coordinates checked. Original mirrored-row draft was corrected.
- These are archived design-tool results, not fresh reruns or electrical bench tests. Passive symbols do not verify MCU internals, firmware or hardware mute.
- MicroPython source compiles according to archived verification, but no flashed MCU/assembly demonstrated. Stop button sends a software request, not a hard electrical audio disconnect.
- Gerbers are historical prototype fabrication artifacts. **Do not manufacture them expecting a standalone hearing-glasses mainboard.**

## 7. Firmware and interface work still missing

No integrated RevF pinout/netlist, complete firmware, proven camera+mic+USB modem concurrency, codec DMA/output, APN reconnect or on-head operating logs are present. Define: sample clocks and A/V synchronization, measured capture rates/codec bitrate, bounded queues, target/session generation, secure server connection, watchdog, audio mute on stale data, modem brownout recovery, charging faults, thermal derating, low-battery shutdown and update strategy. Do not equate an isolated library driver example with an operating complete device.

If a camera is retained only for identifying the selected face while extraction is audio-only, explicitly reconsider required video rate/uplink bitrate and face-to-voice association. Direction-based matching requires a real multi-microphone geometry; single-mic B0441 does not supply it. None of these changes has been implemented in the hardware CAD yet.

## 8. Questions we need the independent expert to answer

1. Is near-head LTE/cloud processing compatible with the intended conversational delay and battery/thermal envelope? Which functions should run locally?
2. Should the acquisition host be P4, another MCU or a Linux SoM? Prove concurrent capture, cellular transport and playback before a custom PCB.
3. Is single-mic capture adequate, or must we add a synchronized microphone array for directional selection? What spacing/clocking/ADC/interface is required?
4. Select exact modem variant/operator bands, antenna and integration constraints. Resolve B7 coverage mismatch, RF layout/head loading and applicable radiated/head-worn testing.
5. Audit complete power stage, burst droop, charger defaults/faults, pack protection, connector bottlenecks and low-voltage operation. Is the500mAh geometry practical at all?
6. Choose/validate BS08 or an available equivalent, codec/driver, hardware limiter and mute; determine measurable coupling/contact preload and vibration feedback treatment.
7. Recommend battery/modem/processor placement for weight/heat/RF, real hinge and flex/cable routing. E's slim CAD is not a constraint if it cannot fit the verified system.
8. Identify required physical prototype tests, measurement equipment, actual estimated prototype BOM/PCB costs and lead times; distinguish prototype modules from production parts.
9. What must change before DFM/assembly/consumer or health-related release? Please return a marked-up architecture, prioritized risks, corrected BOM and staged validation plan.

## 9. Suggested review / build order

First resolve system architecture and required latency on a wired bench; then prove real capture/transport/playback and separation; then LTE evaluation-board concurrency; then power/thermal and transducer output; then new integrated PCB and native enclosure with real parts; finally physical fit, RF, environmental and intended-use evaluation. Do not order an integrated glasses PCB directly from the present RevA files.

## 10. Files, opening and provenance

- Start with this report + BOM_RevF_candidates.csv + FILE_INDEX.csv.
- Open FreeCAD .FCStd in FreeCAD (existing models made with1.1); STEP is neutral exchange. Generator scripts contain hardcoded A:/Focus_Ux paths; copy and adapt paths if reproducing, and preserve manual edits. Do not run generators over originals casually.
- Open KiCad .kicad_pro in KiCad10 with standard libraries; local symbol library/table included. .kicad_prl and FreeCAD backups are excluded as transient/redundant, not design source.
- hardware_revF/docs/POWER_AND_RF.md contains detailed power/RF caveats and original source URLs. hardware_revE/reference has B0441 PDF and BS08 catalog facts; D includes transducer sources; A includes PCB verification.
- Native drawings, STEP/STLs where actually present, screenshots/previews, generators, firmware source, design reports and downloaded reference PDFs are bundled. No AI weights, user recordings, secrets or full software environments included.
- MANIFEST_SHA256.json records every payload file's bytes/hash; packaging verifies archive integrity and payload hashes. This does not rerun CAD/ERC/DRC or validate electrical behavior.
