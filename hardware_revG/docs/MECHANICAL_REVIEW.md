# RevG mechanical engineering study — not manufacturing release

Date: 2026-10-30. Inputs: user RevG brief; expert dossier; RevE build/render scripts and native model; RevF POWER_AND_RF.md. Existing RevA–F assets are untouched. Historical C/D hinge collisions remain valid historical failures. RevE was USB-only; this new study explicitly reserves standalone components.

## Current user requirements and disposition

Egypt; 10–20 engineering units then100 pilot; <=60g target,70g upper conditional limit; >=2h continuous operation and4h typical goal; dedicated unlocked LTE supporting two tested operators. These are targets, not achieved performance. The500mAh reference shape included in CAD does NOT satisfy the runtime requirement and is not the selected battery.

**The generated CAD is an architectural volume/clearance study with rigid, removable temples. Functional folding, RF, battery endurance, complete mass, thermal performance, manufacturability and physical comfort are NOT closed. It must not be fabricated as a finished device.**

## Files and provenance

- `mechanical/FOCUS_RevG_Standalone_Packaging_Study.FCStd`: native FreeCAD1.1.4 study, individually named solids and evidence properties.
- Matching STEP: neutral assembly exchange; alternative hypothetical battery excluded.
- `mechanical/build_revg.py`: reproducible geometry and collision calculations.
- `mechanical/cad_checks.json`: actual validity, static and sampled-motion results, complete pair names/overlap volumes.
- `mechanical/mass_and_cg_estimate.csv`: every modeled item, geometric centroid and either explicit mass assumption or UNKNOWN.
- `previews/RevG_*.png`: renders from actual FreeCAD solids, not generated product photography.
- Assembly drawing SVG is schematic dimensioned assembly guidance, NOT manufacturing toleranced part drawings.

## Source-sized versus provisional geometry

Historical documented envelopes from `hardware_expert_review/EXPERT_REVIEW_DOSSIER.md` and manufacturer references in RevE/F:

| Item | Source body size | What the CAD actually represents |
|---|---|---|
| Arducam B0441 |62x9x6mm|Bounding box only; lens registration, cable and connector geometry provisional|
| SIMCom A7670E |24x24x2.3mm|Bare module inside **assumed30x42x8mm complete-board allowance**; board not proven to fit|
| BS08 pair |each13x7.4x5.6mm,1.7g catalog|Bare body; contact orientation and vibration coupling need sample|
| Tattu500mAh historical reference |58x18x8mm,14g catalog|Nested illustrative reference only; NO duration or selection claim|
| Protected-pack compartment |65x22x12mm|Engineering allowance, NOT an orderable pack|
| Host/hub/memory solution |24x48x10mm|Provisional complete-board volume; not ESP32-P4 die/package dimensions|
| Power/audio solution |24x42x10mm|Provisional solution volume; regulator inductors/thermal may exceed it|
| Nano-SIM solution |16x15x3mm|Provisional PCB/socket allowance plus top service insertion space|
| Four mic daughterboards |each4x4x2mm|Generic allowance, NOT IM69D130 controlled geometry|

References: [B0441 supplier](https://www.arducam.com/), [SIMCom product](https://cn.simcom.com/product/A7670X.html). Exact historical PDFs and catalog extracts are retained under RevE/reference and RevF/reference; this study did not remeasure any purchased component. Do not order or route from these simplified bodies.

## Array and routing

Mic nominal centres in the assembly coordinate system, mm: FL(-60,-7,27),FR(60,-7,27),TL(-94,62,27),TR(99,62,27). Four channels require a proven shared-clock acquisition path and calibrated port delay. Positions alone do not establish beamforming or face-to-voice accuracy. Front ports are pocketed but acoustic mesh/sealing and port geometry need design. Temple microphones face their service cavities in this study; actual external ports remain a blocker.

Red cylinders reserve insulated longitudinal wire corridors and bridge wire volumes at the temple roots. They are included in static and motion collision tests. These are conservative local envelopes, not complete connector mating geometry or qualified controlled-impedance USB/flex. All flex bend radius, loop slack, routing through detachable joints, shielding and fatigue tests remain open. Two floating BTL pairs must remain insulated from chassis/ground.

SIM access is from the top with the service lid removed. There is no sealed user card door. PCB mounting bosses, actual screw/thread selection and connector insertion tooling remain incomplete. Battery area contains no through-pouch screw; supplier-controlled swelling, insulation and crash retention allowance still required.

## Battery feasibility — explicit unmet requirement

Using3.7V nominal and **70% usable energy engineering assumption**, required capacity is:

| Load scenario (NOT measured) |2h continuous|4h continuous|
|---|---:|---:|
|2W|1544mAh|3089mAh|
|4W|3089mAh|6178mAh|
|6W|4633mAh|9266mAh|

Formula mAh=1000*P*t/(3.7*0.70). This does not select a pack, guarantee discharge peaks, or predict actual average consumption. The500mAh reference would supply0.5*3.7*0.70=1.295Wh under these assumptions (38.9min at2W;19.4min at4W). A hypothetical75x28x14mm larger envelope is displayed separately, with NO capacity assignment, mass or fit claim. Obtain a real supplier pack drawing for the measured load/runtime before replacing the selected-assembly reservation. Never shrink a CAD battery to imply capacity.

## Mass and balance

Polymer geometry uses **assumed1.15g/cm3**, no infill reduction; BS08 uses manufacturer catalog1.7g each and reference cell14g. The CSV reports UNKNOWN for camera, PCBs, modem, cables, antenna, lids' retention hardware, optical lenses, nose pads and fasteners wherever unmeasured. The JSON subtotal centre of gravity is only that assumed subset and must NOT be quoted as product centre of gravity. A complete <=60g or <=70g claim is impossible with missing mass. Add weighed actual components and a qualified larger pack, then compare. Even a subtotal below70g is not a pass.

## Collision and hinge evidence

Static Boolean common-volume checks and native shape validity are performed on the generated assembly. Nested source bodies within PCB/pack reservation volumes are intentionally excluded from duplicate collision counting. Thermal and service volumes are kept separate from physical interference tests; they require their own engineering review. Touching faces have zero-volume intersections and do not prove assembly tolerance.

Candidate hinge roots are(-74,6,26) and(74,6,26), z-axis inward rotation. Tests sample0–90degrees at5degree increments for left-only, right-only and simultaneous folding, with body/component/wire shapes included. Every new collision pair and volume is retained in JSON. **This is sampled screening; it does not check every continuous angle. Any failure rejects folding; even zero sampled failures would require continuous clearance and flex analysis.** The architecture therefore stays rigid/removable and production folding is unresolved. No previous failure is overwritten.

## RF, heat, tolerances, and release blockers

Rear antenna keepout is currently only15x23x16mm: it **cannot contain the historical42.6x12.1mm flex flat**. This is an explicit failed placement, not a selected antenna design. Antenna must change with verified two-operator bands or packaging must grow; electromagnetic head/body detuning cannot be evaluated by Boolean CAD. No gain claim.

Host has a22x46x4mm overhead thermal reserve. It is not a heat sink calculation and cannot demonstrate safe skin/battery temperatures. Battery and RF require physical separation from hot switching elements; bench thermal maps and RF tests determine revised layout.

Walls nominal1.5mm, lids1.2mm and0.3mm lid gap are design assumptions; do not treat as manufacturing tolerances. Pocket allowances0.3–0.4mm are prototype nominal values only. Material/process shrink, printer/molder capability, sealing, screw pullout and skin material require supplier DFM. No production STL/Gerber release is made by this mechanical package.

Next: actual component/pack measurements -> board placement with real mating connectors -> continuous hinge redesign including flexible harness -> measured finished mass/CG -> thermal/RF bench -> non-powered physical fit -> controlled powered wear test. Physical comfort,2h endurance and manufacturing readiness remain untested.

## Compact styling screen, separate from baseline

The additional `mechanical/compact_direction` FreeCAD/STEP model narrows the temple shells and provides matching top/front/isometric CAD projections plus a self-contained SVG review drawing. It is kept separate from the first-pass files so the initial 98.86g result remains auditable. The compact screen calculated **90.51g partial assumed mass**, valid native solids, zero selected static collisions, **16 failed sampled folding poses**, and the same failed historical antenna fit. It therefore still fails the 60/70g targets before missing component masses. This is not a manufacturable or comfortable Meta-scale eyewear design.

The latest compact screen also offsets the camera to the viewer-right brow: provisional board body x=4–66mm, front aperture centre x=55mm, and relocated front-right microphone centre x=72mm. The baseline mic coordinates earlier in this document still describe the original first-pass study. These changes preserve zero selected static overlaps in the updated compact screen. **They do not prove the real B0441 lens axis or cable can line up with that aperture**, nor verify optical field of view or acoustic isolation; check the supplier drawing/sample before hardware release. The capture LED appears in the styling image only and still needs a physically routed, independently verified indicator design.
