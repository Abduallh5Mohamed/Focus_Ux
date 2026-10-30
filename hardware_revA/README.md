# FOCUS Rev A - wired proof-of-function hardware

**Status: engineering prototype, not a manufacturing release.** CAD geometry and PCB connectivity checks have been performed. Nothing has been physically assembled, electrically powered, worn or tested for audio improvement/latency. The original software product and GPU experiments are separate.

## Open the two native designs
- `mechanical/FOCUS_Glasses_RevA.FCStd` in FreeCAD 1.1: six printable parts, actual KiCad bare PCB imported, conservative module/cable envelopes. CAD dimensions are generated from the included Python source; changing descriptive properties alone will not regenerate shapes.
- `electronics/focus_control.kicad_pro` in KiCad 10: editable schematic and routed PCB. The project contains its local schematic symbol library. Standard KiCad footprint/3D libraries are required.
- `previews/assembly_isometric.png`, `assembly_front.png`, `assembly_top.png`: rendered from the actual native FreeCAD model, not an AI concept image.
- `electronics/schematic.pdf`, `electronics/pcb_top.pdf`: reference drawings.

## Architecture that these files actually implement

1. A Waveshare GC2093 2MP USB Camera (A), selected as a **candidate**, supplies UVC video and its onboard microphone directly to the host USB system.
2. The custom board is a passive **Pico H control carrier** only. Its two dry-contact input connectors issue SELECT/STOP events through Pico USB serial firmware. It does not digitize audio, transport camera data, run Dolphin, amplify sound or act as a medical hearing aid.
3. The host computer synchronizes media, selects/tracks the target and performs separation. The existing RTX3060 laptop is the first validation host; inference/latency results for this hardware build are not yet available.
4. Output uses a separately connected wired headset. An external host/hub supplies USB power. No battery, charger, radio, on-frame AI compute or optical display has been designed.
5. Camera+mic share one purchased module to reduce integration variables; this DOES NOT guarantee synchronized capture timestamps. That is measured during bring-up.

## Geometry and mechanical assumptions

All dimensions are millimetres. X is left-right, Y points rearward along temples, Z is up. Front frame nominal width146; openings50x34 each, no fitted prescription lenses. Pivot X positions+-70; M3 clearance3.4. Separate arms have provisional ear hooks and strap holes. These are bench-fit assumptions, not anthropometric measurements.

The camera's published envelope38x38x19.01 is represented as a box. The 44x44 cradle has an open front and strap slots. Actual screw pattern, lens centre, microphone apertures, connector placement and cable bend clearance have NOT been derived from a dimensioned manufacturer drawing. Test and revise around the purchased module before printing the final cradle. Do not clamp a microphone aperture or exposed components. Camera retention and attachment fasteners remain a physical-review gate.

The right-side control pod is79x44x28 (plus2mm lid). The carrier65x32x1.6 has four2.4mm mounting holes. Raw KiCad STEP uses (u,-v,z). A rigid +90deg Z rotation then translation(83,30,-4) gives assembly(83+v,30+u,z-4); no reflection or Y normalization is used. Exported bare dielectric thickness is1.51mm versus nominal finished board1.6mm. The pad layout/USB orientation must be rechecked against actual module mounting before assembly; the four-hole pattern alone is symmetric and cannot prove orientation. The cable throat faces negativeY. Lid notches clear the mounting ears.

Conservative Pico/socket/USB plug envelopes are included, not manufacturer-complete 3D assemblies. A20mm above-carrier-bottom component envelope is reserved; exact socket mating height and cable plug shape are unresolved. The3mm underside cavity provides provisional space for generic socket soldertails (~1.5mm in the stock STEP); actual soldering/fastener clearance needs measurement. Switches remain offboard via a harness exit. No switch holes are invented before selecting the actual switches.

**This is intentionally a bulky wired rig**, particularly the camera and side pod. Balance, nose support, face clearance, ear fit, hinge durability and strain relief need iteration. The CAD demonstrates mounting and packaging; it does not establish comfort or safe wear.

## Checks completed

- Mechanical BRep: each of6 printable parts is valid and contains exactly one solid.
- Printable-part intersection check: zero positive-volume intersections above0.01mm3. This does not certify cable/module fit, fastener engagement, tolerances or hinge motion.
- KiCad electrical checks: ERC0 errors/warnings; DRC0 violations/unconnected; schematic parity0; connected-pad comparison5/5 nets equal. Independent physical pin-orientation check40/40 against the stock Pico footprint. An initial mirrored pin-row draft was caught in review and corrected in copper and all exports. Passive schematic symbols mean these checks do not validate Pico internals, firmware or a powered assembly.
- STEP and STL exports generated. STLs are translated to positive coordinates, **not optimized print orientations**. Choose orientation/supports in a slicer after reviewing strength and clearances.
- MicroPython source compiles syntactically. No MCU flashing, electrical test or host integration has been performed. SELECT/STOP events are only commands until the host application explicitly handles them.

See `mechanical/geometry_validation.json`, `electronics/erc.rpt`, `drc_parity.rpt`, `connectivity_check.json` and `docs/VERIFICATION.md`.

## Prototype build sequence

1. Review the electronic schematic and verify actual purchased pin numbering, diode polarity, socket dimensions and mating height. Finalize unresolved BOM entries.
2. Obtain camera/module and cable samples. Measure external envelope, ports and acoustic/optical apertures; update cradle and plug keepout in `mechanical/build_mechanical.py`.
3. Print inexpensive fit coupons for camera tray, PCB boss and Pico USB throat before all parts. Hole dimensions depend on printer/material and actual fasteners; adjust pilot sizes accordingly.
4. Trial assemble cold/unpowered. Check that the head/face cannot contact exposed conductors, raw screws or lens edges. Add appropriate padded supports/strap and strain relief; current CAD does not complete these.
5. Electrically bench-test the carrier, GPIO inputs, USB enumeration and LED before attaching to a person. Use `electronics/README.md` bring-up procedure.
6. Flash appropriate official Pico MicroPython firmware, then copy `firmware/main.py`; run a serial event observer. It does not ship a compiled UF2.
7. Connect camera and headset independently, measure media sync and end-to-end latency and re-run known source separation tests. Only then integrate controls into the actual app and conduct a supervised user evaluation.
8. Review DFM/DFA with an electronics/mechanical engineer and chosen manufacturer before any production order. Prototype fabrication files are not an approval to mass-produce.

## Files for a reviewer

`mechanical/`: native FCStd, assembly STEP, six STL parts, generator, parameters, geometry report.
`electronics/`: native KiCad files, local symbol library, routed board, schematic/PCB drawings, BOM, placement, Gerber/drill, STEP and check reports.
`firmware/`: MicroPython control/event source and host serial observer.
`docs/`: verification and open engineering decisions.

## Sources (primary)
- Camera candidate: https://www.waveshare.com/product/ai/cameras/single-cameras/gc2093-2mp-usb-camera-a.htm (published38x38x19.01mm, onboard mic, USB,5V+-5%,180mA nominal operating current). Actual stream modes/current/sync must be measured.
- Pico dimensions/pinout: https://datasheets.raspberrypi.com/pico/pico-datasheet.pdf and https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html . Pico H is a controller, not the inference processor.
- Additional connector/LED primary references and unresolved MPNs are in electronics/README.md and BOM.csv.
