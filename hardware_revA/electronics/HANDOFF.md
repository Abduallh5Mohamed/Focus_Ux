# Electronics handoff

Completed native editable KiCad10.0.7 project under this folder. Scope is an offboard-Pico-H **control-only** carrier for the wired proof-of-function rig. It does not process camera/audio/model data and does not imply standalone glasses capability.

Evidence:

- `erc.rpt`:0 errors,0 warnings.
- `drc.rpt`:0 violations,0 unrouted pads.
- `drc_parity.rpt`:0 schematic parity issues as well as0 DRC violations/unconnected pads.
- `connectivity_check.json`: exact5 connected-net pad membership matches after root-sheet prefix normalization.
- `physical_orientation_check.json`:40/40 pad coordinates match the rotated stock Pico module footprint. **Final USB-left mapping: J1 physical1..20 at y24.89; J2 physical40..21 at y7.11.** Initial mirrored row layout was caught by independent review and actually rerouted; see `PHYSICAL_ORIENTATION.md`.
- `manufacturing/`:7 Gerber layers + drill. Prototype fabrication outputs; procurement/fit review pending.
- `schematic.pdf`, `schematic_svg/focus_control.svg`, `pcb_top.pdf`, `pcb_preview.svg` exported using KiCadCLI.
- `focus_control_board.step`:65x32x1.6mm bare-board mechanical reference.
- `carrier_generic_components.step`: generic library component assembly, omits Pico module.

Shared pin map: GP2 SELECT_N, GP3 STOP_N internal pullups; active-low dry contacts. GP4 through1k to LED anode; cathode ground. J1.3 ground. Firmware intentionally owned by parent, none created here.

Critical open points: exact socket mating height and vendor footprint acceptance; external switch selection/actuator holes; LED and resistor procurement; module insertion/USB plug mechanical clearance; current/thermal and electrical bring-up; end-to-end timing/quality. `BOM.csv` explicitly marks unresolved selections. Board and generic model dimensions are draft engineering geometry, not a production approval.

Native project includes local symbols and embeds stock footprint geometry; installed KiCad10 3D models were resolved successfully. Re-running generator overwrites native files and UUIDs; manual edits must be preserved before regeneration. All exports were regenerated after final net/library-ID/UUID fixes.
