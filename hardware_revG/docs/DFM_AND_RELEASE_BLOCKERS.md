# RevG DFM review and release blockers

Date: 2026-10-30. Status: **engineering review only; no manufacturing release**.

## What was actually checked

The baseline and compact FreeCAD solids were generated, exported to STEP, and screened for native shape validity, static common-volume collisions and inward-folding poses every 5 degrees. The compact screen has no selected static overlaps but 16 failed sampled fold poses; continuous motion and flex fatigue were not verified. Its partial mass is 90.51 g, excluding multiple required parts and a qualified battery. The historical flex antenna does not fit its provisional keepout.

The KiCad file is a partial, bench-size 210 × 180 mm subsystem/interface drawing. The current CLI reports contain 49 ERC violations, 4 hole-clearance DRC violations and 91 unconnected pads. It is neither a complete schematic nor a routed, eyewear-size PCB. No Gerbers were released.

## DFM items requiring engineering resolution

| Area | Current issue | Required evidence before release |
|---|---|---|
| Mechanical fit | Candidate housing still exceeds 70 g on a partial mass count; no actual board/pack assembly fit | Supplier drawings, weighed parts, complete assembly stack and measured CG |
| Lens and nose fit | Frame is a packaging approximation | Optical vendor lens retention design, nose geometry, strength and fit trials |
| Folding and service | Candidate hinges intersect; removable arms have no qualified latch | Continuous sweep with parts and flex, tolerance stack, cycle/drop/service testing |
| Battery | 500 mAh is historical reference only; no qualified 2 h pack | Measured power profile and selected protected cell drawing, charge/NTC/peak-current checks |
| Thermal | Clearance only, no heat path calculation or measurements | Full-load temperature maps at skin, cell and modem, worst-case ambient |
| RF and SIM | Antenna keepout fails; exact modem SKU/bands and SIM mechanics open | Two-operator compatibility, antenna matching, on-head OTA and insertion/service tests |
| Audio safety | Draft BTL amp/attenuation has no measured output limit | Correct symbol/land pattern, independent mute and limiter, contact/output tests |
| Acoustic array | Four schematic mic symbols, no qualified acoustic ports/clock routing | Synchronous four-channel capture and phase/calibration test in the assembled frame |
| Board manufacturing | ERC/DRC fail; PCB is bench-sized and unrouted | Complete power/RF/USB/audio schematic, layout, fab stackup, clean checks and human review |
| Environment | Open seams, ports and exposed contacts | Sweat/rain/ESD/cleaning, material and corrosion testing |

## Explicit blockers to sale, fabrication, or a "finished" product claim

1. The user's 60 g target and conditional 70 g upper limit are already exceeded by the compact **partial** mass model.
2. Two-hour continuous and four-hour typical endurance have no measured power budget or fitting qualified pack.
3. Capture-to-bone-conduction p95 ≤150 ms has not been measured on LTE; if p95 exceeds 200 ms, the experience cannot be called live listening under the user's criterion.
4. Speaker-selection/separation quality and face-to-voice matching have no verified product-level evidence; wrong-person or uncertain-state handling remains a required gate.
5. Exact modem/operator compatibility, RF antenna performance, thermal/skin safety, BC output safety and user comfort have not been demonstrated.
6. The RevG KiCad project is incomplete, ERC/DRC fail, no routing, fabrication package, assembly or physical prototype exists.

## Decision for the next build

Preserve the everyday-glasses styling as the industrial-design target. First measure a complete camera/four-mic/LTE/host/audio bench stack under real network load, including p50/p95/p99 stage timestamps and battery-current peaks. Then choose physical architecture from measured power and latency: redesign the integrated frame only if mass, battery and heat can close, or explicitly re-scope hardware if they cannot. A prettier shell cannot solve those three constraints. No production order should use these files.
