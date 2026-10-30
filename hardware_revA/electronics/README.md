# FOCUS wired control carrier — RevA engineering prototype

Open `focus_control.kicad_pro` in KiCad 10.0.7. Native schematic and routed PCB are provided. `schematic.pdf` and `pcb_preview.svg` are convenience previews. `focus_control_board.step` is the **bare carrier PCB** mechanical reference, not a complete validated assembly.

## Architecture and scope

The original Raspberry Pi Pico H (RP2040, order SC0917) is plugged into two female sockets. It supplies USB serial/CDC **button events only**, and one status LED. It does not process video or audio. Its own USB connector attaches to the external host. The UVC camera with integrated microphone attaches directly to the host or powered USB hub on a separate cable. The carrier has no high-speed USB traces, audio circuit, battery, radio or custom power supply. All unused Pico pins remain isolated. Never connect the camera to GPIO or the control headers.

## Electrical pin map

| Function | Pico physical pin | GPIO | Carrier |
|---|---:|---|---|
| Ground | 3 | GND | J1.3, J3.2, J4.2, D1.1 |
| Select target | 4 | GP2 | J1.4 to J3.1; normally-open external switch to J3.2 |
| Stop/mute command | 5 | GP3 | J1.5 to J4.1; normally-open external switch to J4.2 |
| Status LED | 6 | GP4 | J1.6 to R1.1; R1.2 to D1.2(anode); D1.1 cathode to ground |

J1 socket n maps to physical Pico pin n, on the **bottom row** with USB pointing left. J2 socket n maps to physical Pico pin `41-n`, on the **top row** with USB pointing left. J2 has no connected carrier nets. Module component-side top view: USB faces left along negative X. Inserting Pico backward may not immediately power the carrier, but violates the design; check physical pin1 at(8.37,24.89) before power. Inputs require firmware internal pullups and software debounce (start20ms, then verify). This is an unprotected internal dry-contact interface; no external voltage input. Stop/mute is a software request; it is **not** a safety-certified or electrically hard audio disconnect.

R1=1k: at GPIO3.3V, LED current `(3.3-Vf)/1000`; even a shorted LED draws at most3.3mA through resistor. Actual brightness and Vf require the chosen LED sample. No external power is connected to Pico VBUS/VSYS/3V3 pins by this carrier.

## Mechanical interface

- PCB XY extent0..65 by0..32mm; nominal finished thickness1.6mm. KiCad top view origin upper-left. Actual exported STEP was read with FreeCAD: X0..65,Y-32..0,Z0..1.51mm. The dielectric body omits the surface-layer contribution to nominal1.6mm; reserve the full nominal thickness in mechanical tolerances. Normalize STEP as `u=STEP_X,v=-STEP_Y` before applying board-layout coordinates. This axis conversion is not a physical board reflection.
- Four NPTH holes, diameter2.4mm, centers(3,3),(62,3),(3,29),(62,29)mm.
- Pico board nominal51x21mm; target envelope x7..58,y5.5..26.5. Socket rows: **J1 y24.89 (physical1..20),J2 y7.11 (physical40..21)**; socket pin1 of each atx8.37; pitch2.54mm along+X, socket pin20x56.63. This matches17.78mm row spacing and48.26mm pin span. All40 socket pads were compared to the rotated stock Pico module footprint; see `physical_orientation_check.json` and `PHYSICAL_ORIENTATION.md`.
- J3 select header pads(61,8),(61,10.54); J4 stop pads(61,21.46),(61,24). External switches do not have fixed PCB positions.
- LED cathode pad(3,8), anode(3,10.54). R1 pads(3,19),(3,26.62).
- Housing must preserve USB plug/cable access from the left at y16mm. USB plug shape and minimum cable bend radius are still procurement-dependent.
- Allow a **20mm design envelope above PCB bottom** for sockets/Pico/connector soldering tolerances. This is a conservative design allowance, not a measured or certified assembled stack. Confirm real mating engagement, male-header plastic height, debug connector clearance and LED mounting height before closing the enclosure. Bare STEP omits these components.
- Generic populated STEP connector tails extend approximately1.505mm below the exported board origin; provide at least2mm underside clearance as a draft allowance, then verify chosen parts and trimmed solder joints. Generic model LED bbox: X1.1..4.9,Y-11.17..-7.77,Z-0.905..9.895mm; this confirms negative STEP-Y conversion. Generic sockets reachZ10.095mm before fitting Pico; assembled Pico/socket height remains procurement-dependent.

## Verification performed

KiCad CLI10.0.7:

- Schematic ERC: **0 errors,0 warnings** (`erc.rpt`).
- PCB DRC: **0 violations,0 unconnected items** (`drc.rpt`), default0.2mm clearance; routed tracks0.3mm; no vias in final routing.
- KiCad DRC with **schematic parity enabled:0 footprint/net parity issues** (`drc_parity.rpt`). Symbol UUID paths and full library IDs are assigned; intentional NC pads have their matching isolated nets; mounting holes are marked board-only/excluded from BOM and position files.
- Exported schematic connected nets compared to PCB pad memberships: **5/5 equal**, `connectivity_check.json`.
- Physical pin orientation compared independently to KiCad's stock original-Pico-compatible module footprint: **40/40 coordinates equal**, `physical_orientation_check.json`. See orientation report for the corrected initial row-mapping mistake; ERC alone could not catch it.
- Gerber layers, Excellon drill, PDF schematic and bare-board STEP exported successfully.

The schematic uses local **passive carrier symbols** for the sockets, resistor and LED; ERC therefore checks carrier connections, not the Pico internals or correctness of firmware/power sequencing. NC marks are deliberate. This cannot replace electrical prototype testing. The module is an external assembly listed separately in BOM; four mechanical mounting holes are board-only. Custom pad-net equality and KiCad schematic-parity mode both passed.

PCB embeds stock footprint geometry and refers to standard KiCad10 libraries (`Connector_PinSocket_2.54mm`, `Connector_PinHeader_2.54mm`, `Resistor_THT`, `LED_THT`). Installed `${KICAD10_3DMODEL_DIR}` STEP models resolve and exported successfully into `carrier_generic_components.step`. Those models show generic sockets/headers/LED/resistor, **not supplier-specific verified parts and not the Pico module**. `Focus.kicad_sym` and project-local `sym-lib-table` are included so schematic symbols do not require external installation.

## Manufacturing status

`manufacturing/` contains prototype fabrication outputs only. Do not order production as a released wearable design. The routed board has no intentional unrouted nets, but connector supplier drawings, exact switch and LED selection, socket mate height, real mechanical fit, USB throughput/power budget and assembled electrical tests are pending. Generic KiCad footprints do not establish supplier compatibility. All unresolved MPNs are explicitly marked in BOM.csv.

Bare-PCB draft spec:2-layer FR4,65x32mm,1.6mm,1oz copper nominal, soldermask both sides, no controlled-impedance requirement (no high-speed signal routed). Factory must review NPTH/PTH processing and supplied drill. No impedance or safety certification claimed.

## First assembled-unit test (not yet performed)

1. Inspect board and verify no shorts between connected GPIO nets and GND before installing module.
2. With module disconnected, meter J3/J4: normally open switch only, no foreign voltage.
3. Plug correctly oriented Pico H; USB power from current-limited host/hub. Confirm boots and CDC enumerates before connecting audio pipeline.
4. Confirm each button's GPIO reads high released/low pressed, firmware debounces and host receives the correct event. Verify LED operation.
5. Connect UVC camera independently, enumerate actual audio/video modes; verify microphone present on purchased camera variant. Measure stream timestamps and host load.
6. Measure end-to-end audio latency, electrical current, surface temperature and behavior on unplug/failure. Test wired headset volume conservatively; the carrier does not amplify or limit audio.

## Primary references

- [Original Raspberry Pi Pico datasheet](https://datasheets.raspberrypi.com/pico/pico-datasheet.pdf): module dimensions/pinout, GPIO and power information. Datasheet is the authoritative source; pin labels cross-checked.
- [Raspberry Pi Pico documentation](https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html): Pico H module and header distinction.
- [Samtec SSW-120-01-G-S candidate](https://www.samtec.com/products/ssw-120-01-g-s): require series print review before final design-in.
- [Kingbright WP3A8GD candidate](https://www.kingbrightusa.com/images/catalog/SPEC/WP3A8GD.pdf): candidate LED; confirm purchased part and footprint compatibility.

## Reproduce

Run `A:/Kicad/bin/python.exe build_carrier.py`, then KiCad CLI ERC/DRC/export. Run schematic XML export followed by `A:/Kicad/bin/python.exe verify_netlist.py`. Generator overwrites local design files only; preserve manual edits separately before regeneration.
