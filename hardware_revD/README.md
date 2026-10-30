# FOCUS RevD — wired bone-conduction bench design

**Engineering prototype CAD, not manufacturing release or physically demonstrated hearing device.**

This revision adds two removable inner-temple transducer cradles and separate retaining/contact-cover plates. The transducer objects are published-size **bounding envelopes**, not detailed supplier CAD. The capture board remains the actual official Seeed STEP used in RevC; purchased camera revision must match before fit approval.

## What is delivered

- Native editable FreeCAD assembly, STEP exchange, individual STL exports, reproducible source and exact-BRep screening scripts.
- Two Adafruit1674 nominal21.5×14×7.9mm envelopes;9.6g each,19.2g pair before mounting/wiring. Supplier documentation conflicts on impedance/max power; see audio document.
- Ten mechanical parts: chassis, service door, two temples, two ear sleeves, two cradles and two cover plates.
- Nominal0.25mm transducer-pocket clearance. Separate0.8mm provisional insulating cover plates with0.7mm bosses reach the assumed envelope face and geometrically block outward escape. This is nominal contact with no established preload. Cover screw bores1.3mm; clamp bores1.8mm. Fastener selection/thread engagement, material and retention loads are not validated. A provisional2.8mm rear wire exit still needs terminal-position/strain-relief verification. Rectangular temple clearance is a packaging approximation; actual clamp shims/fit need a sample.
- Rearward hinge axes at(X,Y)=(-68,24) and(73,24)mm.2.7mm nominal bores accept a2.5mm geometric gauge; no physical pin/tolerance/retention proof.

## Critical known limit

**Final complete-assembly screening fails: the right transducer carrier hits the chassis at90°; folding the two temples together also produces collisions.** Left independent motion clears at sampled5° increments. The earlier arm-only broadphase omitted some accessory collisions; it was corrected to include the whole moving assembly before the final result. Read `tests/virtual_test_report.json` for the latest complete result; `initial_motion_failure.json` is historical and superseded. Do not advertise fold-flat storage or print this as a finished wearable. Bench use is open-position only until the hinge arrangement is redesigned and retested. No test failure has been removed from the acceptance result.

The separate cover improves geometric retention compared with an open pocket; it does not establish safe pressure, vibration transfer, skin-contact suitability or a working audio output. Exact contact location/face, adjustable preload and compliant isolation remain physical design gates. Rigid mounting may feed vibration back into the capture microphone.

## ESP32-S3 and signal path

ESP32-S3 captures camera/microphone data and transfers it by Wi-Fi. It does not run Dolphin or power the bone transducers. Simultaneous audiovisual capture, timestamps and frame cadence are **not demonstrated** by CAD.

First bench path: capture board → Wi-Fi → GPU computer/Dolphin → USB audio DAC → offboard limited stereo amplifier → separate wired transducer pairs. The return is wired. Firmware, host streaming and end-to-end real-time behavior are not delivered or proven by this hardware revision. See `docs/AUDIO_ARCHITECTURE.md` for sourced component candidates and wiring.

## Files

- `mechanical/FOCUS_RevD_Industrial_Review.FCStd`: native assembly.
- `mechanical/FOCUS_RevD_Assembly.step`: exchange assembly.
- `mechanical/stl/`: prototype part geometry, not print/manufacture approval.
- `previews/RevD_isometric.png`: direct native CAD rendering; transparent covers reveal envelope references.
- `mechanical/build_revd.py`: full reproducible builder; requires FreeCAD Python.
- `tests/test_revd_virtual.py`: static, sampled-motion, packaging and nominal cover-blocking tests.
- `tests/virtual_test_report.json`: actual results; overall failure remains if paired folding fails.
- `docs/AUDIO_ARCHITECTURE.md`: offboard amplifier/DAC proposal and source conflicts.

## Before functional demonstration

Obtain exact parts and verify dimensions/identity. Choose real screw retention, insulated covers, cable exit/strain relief and an adjustable head-fit interface. Validate amplifier startup/mute/output on dummy loads, then actual vibration and feedback with appropriate instrumentation. Measure full capture-to-output latency, current/heat, assembled weight and comfort. Full camera field of view, antenna/microphone access, lens retention, stress/fatigue/drop and environmental protection are still untested. There is no battery or SIM inside the frame in this revision.
