# FOCUS Rev C — independent engineering review

Review scope: architecture, source provenance, mechanical packaging assumptions and release gates. This is a design review, not a physical test report. Review date: 29 October 2026.

## Release status

**Engineering packaging prototype. Not a manufacturing release.** A polished exterior and manufacturer component geometry make the fit study more credible, but cannot prove optical performance, thermal safety, wireless performance, comfort or low latency.

It is reasonable to freeze a reviewed *external form* for presentation while keeping the mechanical fit and electronics release provisional. Label these states separately. Do not call the development board a complete custom electronics design.

## Component provenance and known limits

The reference component is the manufacturer-provided `Seeed Studio XIAO-ESP32-S3-Sense.step`, obtained through Seeed's official resources. The supplied source contains 103 solids; source-axis bounds reported by the CAD importer are X −8.973 to 15.390 mm, Y −0.250 to 13.710 mm, Z −15.001 to 2.779 mm. These extents describe the supplied CAD, not a dimensional inspection of a purchased sample.

The planned rigid placement is rotation 180° about X, then translation (63.75, 0.25, 10.25) mm. Thus the expected global bounds are X 54.777…79.140 mm, Y −13.460…0.500 mm, Z 7.471…25.251 mm. Axis reassignment does not make the physical component thinner. A lens centre estimated from the CAD bounding geometry at source (8.75, 10.83, −6.75) becomes global (72.50, −10.58, 17.00) mm; this is a construction reference, not a measured optical axis or field-of-view specification.

Seeed's current documentation lists a 21 × 17.8 × 15 mm Sense assembly, camera, microphone, 2.4 GHz Wi-Fi and BLE. It also documents camera revisions and mixed shipments. An older STEP can differ from the unit purchased. The official product dimensions and imported STEP envelope are therefore complementary references, not interchangeable guarantees. [Official Seeed documentation](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/)

Before committing any aperture, purchase and identify the exact camera/board revision. Check lens position, full field of view, USB plug envelope, connector access, microphone acoustic port, antenna connector and antenna position against the sample.

## Architecture findings

1. **Keep inference external initially.** The module captures and transports audiovisual input. There is no demonstrated Dolphin inference port running on it. A phone or host/server processes the stream; phone audio output remains the first return path.
2. **Phone gateway is a deliverable, not an assumption.** Prove the glasses-to-phone link, Internet uplink and returned audio simultaneously, including locked-screen operation, network changes and reconnects. Wi-Fi association alone does not demonstrate that the phone can route both links as intended.
3. **Latency must be measured end to end.** A two-second capture batch imposes capture waiting before upload, queue, model processing and playback. Low inference time alone cannot demonstrate immediate listening. Report capture-to-ear median, p95 and maximum, plus run duration and queue growth. Delayed replay must be labelled as delayed replay.
4. **Synchronize at capture.** Audio/video sequence numbers and timestamps must survive transport. Test head motion, face loss, speaker change, dropped video, network stalls and stale output after reconnection. A wrong target or old sentence played as current is a product failure even when the audio sounds clean.
5. **Power and heat remain open.** Do not quote runtime from sleep current or microphone-only operation. Measure concurrent camera + microphone + Wi-Fi current and peaks with the intended firmware. Test sustained operation inside the closed housing. A hot chip's operating-temperature rating does not establish a comfortable skin-contact temperature.
6. **Antenna and enclosure need a defined relationship.** Reserve the actual antenna, connector and cable bend region. Do not place a metal hinge, battery or conductive coating in an assumed antenna clearance. Verify antenna guidance for the exact purchased assembly and measure the final worn arrangement.
7. **The enclosure cannot establish wearability.** Measure mass, centre of gravity, slip, clamp force, skin pressure, nose load and eyeglass compatibility. Conduct supervised stationary fit tests before walking tests. The development-board lens projection constrains how slim the right-front pod can become.

## CAD acceptance checks

- Keep the imported manufacturer component as a separate, named reference assembly; never export it as printable enclosure material.
- Rigidly transform the complete module, including its connectors, rather than stretching it to fit a design.
- Check every enclosure solid for validity and actual common volume with each component solid; bounding-box overlap alone is not a collision test.
- Check enclosure-to-enclosure collision only for parts meant to be separate; document intended mating faces and assembly positions.
- Include clearance for the USB plug and insertion direction, not just the metal socket; reserve cable bend and strain relief.
- Ensure the lens aperture clears the full field of view, and provide a verified route for the microphone acoustic port. CAD lens-centre alignment alone is insufficient.
- Identify how each lid is retained, how the electronics are retained independently, how tools reach the fasteners, and how the product is assembled without forcing or trapping cables.
- State the prototype process, material, minimum wall, fit allowance, fastening method and print orientation. Injection-moulding draft, shrinkage, parting and tool access need a separate DFM review if that process is selected.

### Generator review findings

The first `work/build_focus_revc.py` source was inspected read-only. Its true-maker geometry, separate reference groups, component-clearance subtraction and explicit status properties are useful improvements over a decorative volume model. The following construction details remain provisional:

- The temple channel is a loft between Y = 23 and 99 mm. It is not demonstrated to open to the underside or connect continuously through the hinge and front pod. Do not describe the current void as an implemented cable route.
- The service door has clearance holes but no reviewed matching bosses, thread engagement or fastener stack. A door shape alone is not a retained assembly.
- Nose pads are labelled reference geometry and have no demonstrated attachment. They cannot be counted as an engineered load-bearing nose interface.
- Static solid-intersection checks do not demonstrate hinge sweep, folding clearance, cable flex life or fatigue strength. Check those independently before wearing the assembly.
- The full assembly STEP includes reference lenses and the manufacturer assembly. It is an inspection assembly; the separate enclosure STLs are the fit-study parts. Do not send the complete assembly to a printer as one part.

These findings do not invalidate a presentation form study. They do prevent claiming a complete assembled wearable or released production design.

### Generated geometry report reviewed

The delivered `mechanical/validation.json` reports six enclosure parts, each valid and consisting of one solid. It records no static enclosure-to-enclosure intersections and no enclosure-to-manufacturer-assembly intersections under the generator's >0.05 mm³ reporting threshold. The imported manufacturer reference retains 103 solids. This closes the reported static CAD interference checks, including the corrected door/frame mating geometry; it does not close the four assembly/wearability blockers above. The native file is source-driven CAD with a datum sketch, not a fully constrained editable manufacturing feature history.

## Evidence required for a manufacturing release

| Gate | Required evidence | Present status |
|---|---|---|
| Exact configuration | Revision-controlled BOM, supplier part numbers and physical module measurements | Open |
| Electrical implementation | Reviewed schematic/PCB, interfaces, power protection and bring-up logs | Open; no new custom wireless PCB established by this CAD |
| Simultaneous media | Continuous camera + microphone + Wi-Fi capture, timestamps, measured bitrate and resource usage | Open |
| Useful processing | Selected-speaker quality and capture-to-ear latency on the actual pipeline, with bounded buffers | Open |
| Mechanical fit | Physical print, assembled sample, connector access, lens/mic clearance and assembly checks | Open |
| Wearability | Measured mass, retention, fit range, thermal performance and participant feedback | Open |
| Power | Current/peak traces, verified supply, runtime and power-loss behaviour | Open |
| RF/connectivity | Worn-link tests, coexistence, gateway behaviour and reconnection | Open |
| Pilot build | Manufacturer DFM, tolerance stack, assembly instructions and unit functional test | Open |
| Product claims | User evidence supporting intended assistance and a defined target-market compliance review | Open |

## Committee-facing statement

“This revision is a manufacturer-CAD-based mechanical integration prototype with a more refined wearable form. It retains external processing. Component fit, live audiovisual transport, end-to-end latency and wearing comfort are separate validation gates; the design is not yet released for mass production.”

Review the native CAD and its generated geometry report alongside this document. Any automated CAD checks report geometric properties only; they do not close the physical gates above.


## Subsequent actual virtual-test finding
Sampled fold sweep failed: right5deg and left30deg have positive-volume collisions with chassis/door. See tests/virtual_test_report.json and TEST_REPORT_AR.md. This is a confirmed CAD kinematic defect, not only an untested release gate. No production release is appropriate until redesigned and retested.
