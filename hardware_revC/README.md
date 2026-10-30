> OUTPUT REQUIREMENT UPDATE: integrated bone-conduction audio is required and currently MISSING from RevC. Existing ear sleeves are not transducers. See docs/BONE_CONDUCTION_REQUIREMENT.md.

> IMPORTANT: subsequent sampled hinge-motion tests FAILED. Right-side collision at sampled5deg, left at sampled30deg. See tests/TEST_REPORT_AR.md. Do not treat static CAD passes as final assembly approval.

# FOCUS Rev C - industrial-design and engineering review

**Status: refined industrial design CAD, NOT a production/manufacturing release.** Actual supplier geometry is included. No physical prototype, powered operation, wearable fit, RF, thermal, audio latency or medical benefit has been validated. Do not present this package as a final working medical device or place a production order from it.

## What changed from A/B
- Integrated tapered capture wing at the upper right frame corner; no external79mm Pico box or38mm camera mount.
- Continuous frame language, smooth lofted/tapering temples, separate ear-sleeve geometry, service door and hinge axes.
- **Actual official XIAO ESP32-S3 Sense STEP**,103 solids, replaces a generic module box. Service cavity is conservatively cleared around actual component bounding boxes. Optical port follows the actual model's camera direction/bounding geometry; optical performance and purchased revision still need verification.
- Source-controlled dimensions, a native datum sketch, BRep checks, native STEP/STL exports and actual FreeCAD renderings.

## Open
- `mechanical/FOCUS_RevC_Industrial_Review.FCStd` - FreeCAD native assembly.
- `mechanical/FOCUS_RevC_Assembly.step` - exchange geometry with actual supplied module.
- `mechanical/stl/` - fit-review shapes, no approved print orientation/material implied.
- `previews/RevC_isometric.png`, `RevC_front.png`, `RevC_top.png`, `RevC_hardware_fit.png` - native FreeCAD views.
- `mechanical/build_revc.py` - generator. This is source-script-driven geometry; changing descriptive properties alone does not rebuild shapes. The datum sketch is construction geometry and does not turn the whole model into a fully constrained feature-history design.

## Meaning of professional here
FreeCAD can create precise BRep geometry and interoperable STEP; changing CAD brands does not establish functional product readiness. This package improves the actual geometry and hardware referencing. A closed release requires verified interfaces, assembly retention, tolerances, fit and physical tests, not only smooth images.

## Hardware reference and transform
Official Seeed wiki links the original source ZIP:
https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/
https://files.seeedstudio.com/wiki/SeeedStudio-XIAO-ESP32S3/res/seeed-studio-xiao-esp32s3-sense-3d_model.zip

Raw reference bounding box mm: X[-8.97334,15.39],Y[-0.25,13.71],Z[-15.0014,2.7786]. Actual overall reference CAD width24.36mm includes protrusions and differs from the quoted21mm board-only nominal dimension. This is why the3D model is used rather than squeezing the whole assembly into a21mm box.

Rigid placement: Rx180 then translation(63.75,0.25,10.25). Result bboxX[54.77666,79.14],Y[-13.46,0.50],Z[7.4714,25.2514]. Lens-block centre derives from raw bounding geometry; its inferred global centreX72.5,Z17 is an engineering datum, not a tested optical-axis calibration. Source is an older camera reference; current sold variants may differ. Match the actual purchased revision before relying on openings, screw access or clearances.

## Functional architecture (proposed, not implemented by this CAD)
Camera+mic+WiFi on frame -> native phone gateway -> local/remote GPU -> returned audio on phone -> headset. Begin with pocket USB power. No integrated battery, charger, SIM modem, custom RF PCB or completed antenna routing is hidden inside the shells. The RevA carrier is not the electronics for RevC.

A cloud server does not eliminate model lookahead, preprocessing, audio/video synchronization or network jitter. Real streaming/latency is a separate measured software milestone. No realtime proof is claimed.

## Geometric checks actually performed
Each of6 mechanical review parts: valid BRep and one solid. Zero positive-volume static intersections with actual supplied module and between mechanical parts above0.05mm3. Reference lenses/nose pads are excluded from print-part claims. Their attachment/optics are not solved by rendering them.

Static checks do not verify hinge motion, fastener preload, print tolerances, stress, wire bend-radius, cable routing continuity or useful worn fit. Internal temple volumes are routing reserves, not a validated continuous harness. Service door has preliminary access holes without final reviewed bosses/engagement. Nose pads are unattached fit references. No assembled validation occurred.

## Release gates before calling this final
1. Freeze the exact supplier/camera/module revision, radio/antenna and power architecture; preserve primary datasheets and component drawings.
2. Verify concurrent A/V transmission and measured processing/returned-audio performance before freezing electronics packaging.
3. Complete actual antenna keepout, mic acoustic path/mesh, connector/cable path and sealing decisions. Select proper protected battery/charger only if needed; do not infer a safe circuit from a reserved cavity.
4. Engineer hinge hardware, service-door retention, cable strain-relief, nose-pad attachment and optical-lens retention with drawings/tolerances.
5. Print fit samples; assemble real components; measure weight/balance, fit, comfort, current/temperature, clamp/hinge durability and failure behavior.
6. Complete relevant electrical/RF/DFM/DFA and jurisdiction/claims reviews with the actual engineering/manufacturing partners, then pilot production and assembly QA.

Names such as FINAL/production-ready should be used only after these gates have real evidence. This revision can be discussed as the industrial-design direction and fit-review CAD.
