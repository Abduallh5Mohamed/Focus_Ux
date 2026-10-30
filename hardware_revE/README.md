> **Updated product requirement:** dedicated onboard Nano-SIM cellular connectivity, onboard battery and no phone gateway. RevE below is a USB form study and does **not** meet this requirement. See [standalone cellular requirements](docs/STANDALONE_CELLULAR_REQUIREMENTS.md) before further hardware work. No modem/battery packaging or performance is validated.

# FOCUS RevE — wearability architecture study

**This changes the architecture and components. It is a professional form/packaging direction, not an approved comfortable or manufacturing-ready device. RevD remains preserved as the bench reference with failed folding tests.**

## Why the previous design felt wrong

The large development assembly dictated the front box. Heavy generic transducers dictated inward-projecting rectangular carriers. A visual polish could not remove those volumes without changing parts. Rigid, fixed contacts also cannot establish a comfortable pressure across users.

## Concrete changes

| Area | RevD bench reference | RevE proposed direction |
|---|---|---|
| Capture | XIAO ESP32-S3 Sense assembly inside the wing | Arducam B0441 USB camera/microphone board across the upper brow |
| Camera packaging evidence | Actual older Seeed STEP | Manufacturer-authored B0441 datasheet:62×9×6mm; bounding envelope, not maker STEP |
| Bone transducers | Adafruit1674,21.5×14×7.9mm,9.6g per unit | BS08 manufacturer catalog:13×7.4×5.6mm,1.7±0.1g per unit; sample/drawing still required |
| Receiver carrier | Large inner box | Smaller rounded capsule, sliding rail, nominal±3mm fore/aft adjustment |
| Frame | Thick bench structure | Narrower rims, continuous brow, tapered temples and separate soft-contact targets |
| Connectivity | Proposed ESP Wi-Fi input, wired output | Wired USB camera/mic direct to external host; no ESP or Wi-Fi in this glasses architecture |
| Compute, amplifier, power | External | External; no battery/amp/AI hidden in thin temples |
| Folding | Failed tests | Selected commercial hinge is still a procurement envelope; folding UNTESTED |

This is **not** a resized1674 or a shrunken XIAO. Old components do not fit the new reserved volumes. Do not order/print RevE expecting to reuse the complete RevD component set.

The B0441 provides a specific camera-plus-microphone candidate, not an unbuilt long camera-flex extension. Its manufacturer document lists USB2UVC and MJPEG video. Actual host compatibility, simultaneous audio/video timing, clock drift, power, heat and model-quality performance still require measurement. USB cable, connector mate and strain relief need detailed routing. No standalone or completely wireless system is promised.

## What the native model proves

Ten mechanical study parts are valid single solids. Static part intersections and source-sized camera/transducer envelope overlap tests pass at the recorded pose. The source checks are in `mechanical/build_reve.py`; exact results in `mechanical/form_study_checks.json`. These are conservative bounding envelopes, not detailed manufactured internals.

The central camera brow preserves the full62×9×6mm table envelope plus nominal0.4mm pocket clearance. Its lens port is a **registration target**; controlled lens-axis, microphone port, connector and fastening geometry are not yet approved. The B0441 drawing was visually reviewed, but it does not establish an exact3D optical datum in this model.

The contact caps have a nominal129mm inner span at this pose. This is one study size, not anthropometric validation or a universal fit. The rail slots provide fore/aft placement; in/out spacers, compliant isolation and a calibrated pressure/retention mechanism are still required. No pressure or safe listening level can be inferred from a CAD gap.

## What must happen before calling it comfortable

1. Obtain exact B0441 and BS08 samples or controlled supplier drawings; record mass, connector/terminal geometry and active contact face. Check supply/sample availability before committing the product schedule.
2. Use a professional optical-frame/hinge supplier or optician to select actual hinges, nose pads, lens retention and at least several fit widths. The displayed hinge/soft interfaces are targets, not manufactured mechanisms.
3. Build a lightweight physical fit rig. Measure complete weight and left/right balance; evaluate nose/ear contact, slippage, receiver placement and adjustment across intended users. Choose a compliant mount and measure its contact force and vibration transfer. One successful static pose is insufficient.
4. Requalify the audio driver for BS08; the earlier1674 settings are not interchangeable. Test electrical output/mute, feedback into microphone and full capture-to-transducer latency before a worn sound demo. Manufacturer power ratings are not listening targets.
5. Select real hinge hardware, model and test folding/cable motion, then strength, fastener retention, heat and production tolerances. No RevE folding pass is claimed.

## Files

- `mechanical/FOCUS_RevE_Wearability_Study.FCStd`: native FreeCAD.
- `mechanical/FOCUS_RevE_Wearability_Study.step`: exchange assembly.
- `previews/RevE_isometric.png`: direct CAD rendering, not AI imagery or physical prototype photography.
- `previews/RevE_component_packaging.png`: transparent packaging view exposing reference envelopes.
- `reference/BS08_catalog_facts.json`: source facts and evidence boundary.
- `reference/Arducam_B0441_datasheet.pdf`: manufacturer-authored source retrieved through a distributor.

Manufacturing STLs are deliberately omitted because this revision contains unresolved interfaces and only a procurement envelope for hinges. Keep the native study editable for component and fit engineering.

## Sources

- Arducam B0441 manufacturer-authored datasheet, board table and dimension diagram on printed page3: https://cdn.robotshop.com/media/A/Adu/RB-Adu-258/pdf/arducam-5mp-autofocus-usb-camera-w-single-mic-windows-linux-macos-android-datasheet.pdf
- Arducam official selection guide lists B0441 as a long camera board with a microphone: https://docs.arducam.com/UVC-Camera/USB2-UVC-Camera-Kit/Specs-and-Selection-Guide/
- BS08 manufacturer product catalog and its published data source: https://bonetransducer.com/#products and https://bonetransducer.com/js/products.js
