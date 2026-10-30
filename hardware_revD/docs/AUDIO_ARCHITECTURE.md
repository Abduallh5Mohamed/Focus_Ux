# FOCUS RevD — integrated bone-conduction audio architecture

Status: sourced engineering proposal for a **bench prototype**. No amplifier circuit, worn-audio performance or end-to-end latency has been physically tested. Mechanical integration of two exciters does not demonstrate hearing benefit. RevD audio is separate from the earlier passive Pico button carrier.

## First functional signal path

```text
Camera + microphone on ESP32-S3 glasses assembly
             │ timestamped video frames + microphone PCM over Wi-Fi
             ▼
External GPU host: receive/synchronize → target selection → Dolphin → playback buffer
             │ USB audio output (decoded PCM)
             ▼
USB audio DAC with measured analog stereo output
             │ L/R analog + signal ground
             ▼
Offboard low-gain stereo amplifier + input attenuation + volume control + mute
             ├── independent twisted pair → left glasses transducer
             └── independent twisted pair → right glasses transducer
```

The first credible bench version puts **both GPU processing and USB DAC playback on the computer**. A phone can subsequently be the user interface, network relay or USB-audio playback endpoint only after its actual OS/device/USB-host compatibility and timing are demonstrated. No Dolphin execution on phone is established by this design. Moving the amplifier off the glasses initially avoids unverified heat, power and PCB packaging inside a temple. Audio return is **wired** in this revision; Wi-Fi uplink does not make the entire glasses system wireless.

Mono isolated speech may be duplicated to both DAC channels in software. This is dual-mono playback, not recovered stereo positioning, binaural beamforming or a directional auditory cue. Do not join amplifier outputs to duplicate a channel.

## ESP32-S3 role and boundaries

ESP32-S3 is the acquisition/control endpoint: camera capture, microphone sampling, sequence numbers, device timestamps, bounded buffers, Wi-Fi transfer, target/button/control messages and status. It does **not** run Dolphin or drive the exciters from GPIO. Its supported Bluetooth is **LE only**; classic Bluetooth and therefore conventional A2DP audio are not available. BLE presence does not establish a working LE Audio/LC3 system. Use the wired audio return above. [Espressif ESP32-S3](https://www.espressif.com/products/socs/esp32-s3), [official Bluetooth support](https://docs.espressif.com/projects/esp-idf/en/v5.2.2/esp32s3/api-guides/bluetooth.html)

Use a camera-capable board with verified PSRAM and a compatible digital microphone. Exact board model/revision, camera sensor, microphone bus/pins, PSRAM mode and pin conflicts must be recorded before writing a pin map. A generic ESP32-S3 module does not automatically include a camera, microphone or free pins. ESP-IDF firmware must capture audio independently of network writes; one slow upload must not stall sampling. JPEG camera capture is a reasonable starting experiment because the official camera driver warns about RGB/YUV memory bandwidth and Wi-Fi contention. No promised resolution/frame-rate follows from that recommendation. [Official esp32-camera driver](https://github.com/espressif/esp32-camera#readme)

Capture clocks/timestamps require validation. Send frame exposure/capture timestamps and audio sample counters, not merely packet-arrival times. On the host, map both into a common clock, detect loss/discontinuity, align/resample honestly and record actual video cadence. Do not relabel sparse camera frames as a genuine25fps mouth sequence. The existing model's visual input assumptions must be checked against captured footage. An ESP camera stream of a room is not a tracked mouth crop until host tracking has processed it.

## Transducer specification and mechanical limits

Candidate: **Adafruit product1674, Bone Conductor Transducer with Wires**. Official product information states21.5×14mm plan dimensions,9.6g per unit,8Ω nominal impedance,1W RMS/2W maximum handling. Two bare units contribute**19.2g**, excluding insulation, mounts, cables and connectors. The quoted electrical rating is a component limit, **not a recommended worn listening level**. [Adafruit1674 product](https://www.adafruit.com/product/1674)

The official dimensional drawing gives **21.5×14×7.9mm overall**, fourR2 corners, and6mm between two central drawing points. Do not interpret that6mm annotation as confirmed mounting-hole centers. The drawing does not provide a specified skin-contact patch, contact pressure, flatness or an approved anatomical fit. Treat the broad21.5×14 face as an **envelope only**, not21.5×14 of guaranteed active contact area. An assumed contact-facing side in CAD must remain labelled provisional until an actual sample is inspected and tested. [Official dimension image](https://cdn-shop.adafruit.com/datasheets/boneconductordim.jpg)

Important source inconsistency: Adafruit's linked supplierPDF gives the same21.5×7.9×14mm dimensions, but its cover/description says4Ω while its electrical table says8Ω; maximum power also differs from the product page. This is unresolved documentation conflict, not a reason to silently select a convenient value. Purchase the exact1674 item, record lot/part identity, measure DC resistance, obtain supplier clarification if it differs, and characterize impedance before amplifier release. Use the product's more conservative1W nominal rating for engineering checks. [Linked supplierPDF](https://cdn-shop.adafruit.com/product-files/1674/C2049_datasheet.pdf)

Adafruit advises insulating the transducer and wire connections for prolonged skin contact because sweat can create a conductive path. A thin electrically insulating contact cover and strain relief are needed, but their material, thickness and contact preload change vibration transfer and require testing. The metal terminals and solder joints must not touch skin. CAD currently establishes neither biocompatibility nor a qualified skin-contact surface. Bone conduction does not guarantee suitability for every cause or degree of hearing difficulty.

## Practical amplifier candidate and wiring

Use **Adafruit987 MAX98306 stereo breakout** as a bench candidate rather than inventing a power stage. Board envelope28.1×24×10.4mm, mass4.6g, published supply2.7–5.5V. At5V the amplifier can deliver more than the transducer's1W nominal rating, so its mere presence is **not output protection**. Its internal thermal/overcurrent features protect the amplifier under some faults; they are not hearing-level limiters. [Adafruit987](https://www.adafruit.com/product/987), [MAX98306 manufacturer datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/MAX98306.pdf)

Initial bench setup: current-limited regulated**3.0V** external amplifier supply, lowest documented9dB jumper setting, analog attenuation and volume initially at zero. Verify exact gain jumper state on the actual breakout revision. A lower rail reduces available swing but is not a calibrated acoustic or fail-safe power limiter. Do not power amplifier from an ESP GPIO or assume its3V3 regulator has spare audio-current capacity. USB DAC power requirements and amplifier supply are separately budgeted.

| Connection | Destination |
|---|---|
| DAC analog left (TRS tip if that DAC uses standard TRS) | Left input attenuator/volume path → amplifier L+ input |
| DAC analog right (TRS ring) | Right input attenuator/volume path → amplifier R+ input |
| DAC signal ground (TRS sleeve) | Amp signal ground; L− and R− **input** terminals tied to ground for single-ended operation |
| External regulated3.0V and return | Amp VDD and GND; check polarity before energizing |
| Amp OUTL+ and OUTL− | Left transducer's two wires, floating pair |
| Amp OUTR+ and OUTR− | Right transducer's two wires, separate floating pair |

The output pairs are **bridge-tied classD**: neither negative output is ground. Never connect output-minus to input ground, never join left/right negatives, never feed an output into another amp, and do not use a common-ground three-conductor headphone cable for these two floating transducers. Use a keyed four-contact connector with a dedicated twisted pair per side; select connector/routing/strain relief physically before release. Keep classD cable length and EMI within the device guidance; head-worn routing may exceed its referenced30cm unfiltered cable arrangement and then needs filter/layout/EMC investigation. [Adafruit input/output wiring](https://learn.adafruit.com/stereo-3-7w-class-d-audio-amplifier/inputs-and-outputs)

A **draft, untested attenuation option**, per channel, is10kΩ series plus1kΩ shunt to input ground, ahead of the breakout's AC-coupled positive input; approximately1/11 nominal voltage transfer ignoring input loading. Add the manufacturer-recommended dual-channel audio volume control, normally-muted startup and host software limiting. Do not treat these as a released schematic: component tolerance, pot loading, DAC output range, noise and actual gain need measurement. Example only: a measured2Vrms DAC maximum ×1/11 ×10^(9/20) is about0.512Vrms output or33mW into an ideal8Ω resistor, below clipping. This electrical calculation is not a measured device result or a safe-human-level claim. Higher gain, a different DAC, clipping, altered divider or wiring fault invalidates it.

## Bench acceptance gates — before a worn demonstration

1. **Identity and fit:** verify bought exciter dimensions, insulation, electrical identity, polarity markings, mass and actual contact-facing surface. Check temple adjustment, cable traction and clearance. Do not clamp a rigid hard-coded contact force onto a person.
2. **Dummy-load electrical validation:** replace exciters with separate8Ω noninductive power resistors of adequate rating. Check supply polarity/current limit, gain, mute, zero-input behavior and both channel outputs. Measure the bridge output differentially using suitable instrumentation; never ground a bench-scope probe clip to an active BTL output. Begin with very low signal.
3. **Output limiting:** measure DAC full-scale amplitude and amplifier output over the intended band/volume settings, clipping and transients. Demonstrate a reproducible electrical cap with margins on the actual loaded hardware. `P=Vrms²/R` applies to the resistive dummy load; a real exciter is frequency-dependent.1W/8Ω corresponds2.83Vrms but is a damage-rating calculation, not the listening target. Do not start a skin-contact test at that level.
4. **Mute/fault behavior:** startup, reboot, network loss, DAC removal, stale audio, application crash and control-button stop must yield bounded playback and reliable mute. Do not keep replaying delayed speech or allow an ever-growing queue. A software mute alone is not a hardware fail-safe.
5. **Capture and inference:** run concurrent camera+microphone+Wi-Fi with logs, validate audio discontinuities/frame loss/synchronization, then measure capture→GPU→DAC→transducer delay and jitter. Compare speech quality against the wired reference before attributing problems to the model.
6. **Mechanical feedback:** test whether exciters mechanically couple into the glasses microphone/camera, producing buzz, feedback, tracking motion or intelligibility loss. Add isolation only after measuring its effect on useful contact vibration.
7. **Fit/comfort/thermal:** only after electrical checks, conduct a short, adjustable, low-output consenting-adult fit trial with immediate stop and no assumption of clinical benefit. Measure temperatures, pressure discomfort and audible leakage. Any user hearing-benefit evaluation requires an appropriate professional plan; ordinary free-air loudspeakerSPL figures do not establish bone-conduction dose or benefit.

## Unfinished work and release boundary

This document selects an architecture and bench candidates. Still missing: bought parts, clarified transducer datasheet conflict, DAC selection/compatibility, exact pin map, tested attenuation/mute circuit, output calibration, contact/mount mechanics, repeatable latency/quality measurements, full power budget and EMC/skin-contact assessment. No custom audioPCB or standalone wireless return is claimed. The ESP32-S3 and integrated exciters make a plausible acquisition/output prototype; they do not establish a medically effective or manufacturing-ready hearing device.

## Local reference copies

`sources/adafruit1674_dimensions.jpg` and `sources/C2049_datasheet.pdf` were downloaded from the official Adafruit product links on2026-10-29 for engineering review. Product-page and linkedPDF differences above are deliberately preserved rather than reconciled without evidence.
