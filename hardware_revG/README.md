# FOCUS RevG review package

An original everyday-eyewear design direction for the FOCUS assistive-listening concept, with a separate engineering packaging screen. The styling image is visual only. **No hardware was built or measured; this is not a release candidate.**

## Open first

1. [Visual design direction](INDUSTRIAL_DESIGN_DIRECTION.md) and [viewer-right camera style concept](previews/FOCUS_RevG_camera_right_concept.png).
2. [Compact CAD assembly review](mechanical/compact_direction/RevG_assembly_review.svg), [native FreeCAD](mechanical/compact_direction/FOCUS_RevG_Compact_Packaging_Screen.FCStd), [STEP](mechanical/compact_direction/FOCUS_RevG_Compact_Packaging_Screen.step), and [check data](mechanical/compact_direction/cad_checks.json). The native file has saved GUI visibility/colors/isometric view; if regenerating geometry with FreeCADCmd, run `mechanical/compact_direction/make_view_ready.FCMacro` in the GUI again before delivery.
3. [Engineering change plan](REV_G_CHANGE_PLAN.md), [open issues](REV_G_ASSUMPTIONS_AND_OPEN_ISSUES.md), and [release blockers](docs/DFM_AND_RELEASE_BLOCKERS.md).
4. [Electronics status](electronics/ENGINEERING_STATUS.md), [KiCad schematic](electronics/FOCUS_RevG_Mainboard_REVIEW.kicad_sch), [KiCad PCB](electronics/FOCUS_RevG_Mainboard_REVIEW.kicad_pcb), [ERC](electronics/reports/ERC.rpt), [DRC](electronics/reports/DRC.rpt).
5. [Candidate BOM](BOM.csv), [cost model](COST_MODEL.md), and [test plan](TEST_PLAN.md).

## Critical result

The compact CAD lowered the **partial assumed** mass from 98.86 g to 90.51 g, but still breaches the 60 g target and 70 g conditional ceiling before required unweighed parts. Folding and antenna fit fail. The partial KiCad drawing fails ERC/DRC and is bench-sized. Neither CAD nor electronics is ready for fabrication; styling and engineering currently diverge.
