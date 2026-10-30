# FOCUS RevG — change plan before design freeze

Date: 2026-10-30. State: ENGINEERING DEVELOPMENT / NOT FROZEN.

## Mandate and evidence

Develop a lower-cost standalone Nano-SIM/battery/bone-conduction architecture toward a real testable product. Existing RevE is USB mechanical study; RevF power/RF proposal; RevA PCB buttons only. No physical glasses, LTE latency, runtime, worn comfort or RF measurements established. Historical C/D folding failures remain evidence. Software file inference measurements do not validate hardware.

Read sources: hardware_expert_review/EXPERT_REVIEW_DOSSIER.md, BOM_RevF_candidates.csv, hardware_revF/docs/POWER_AND_RF.md, hardware_revD/docs/AUDIO_ARCHITECTURE.md; native generators and reports for A–E. Requested FOCUS_Expert_Review_AR.md was not found in the supplied project/attachment search; it cannot be represented as reviewed. Input inventory will be archived.

## Decisions proposed, not manufacture selections

1. Split bench functional integration from wearable packaging. CM5 is a desktop reference only. P4 remains candidate pending simultaneous camera/four-channel acquisition/modem/playback/reconnect tests.
2. Four matched microphones with genuinely synchronous capture. Compare IM69D130 to lower-cost documented candidates; count receiver/clock/decimation costs, not microphones alone. Direct P4 four-channel support must be proved; PCM1864 four-PDM interface is a candidate alternative, not automatic integration success.
3. Retain B0441 as sourced camera baseline; compare a lower resolution/rate and a DVP/CSI camera only if face association accuracy and host bandwidth/power improve in measurement. Four microphone channels do not come from the B0441 mic.
4. Keep A7670E SKU/revision, operator bands and antenna unresolved until verified. Resolve earlier FXP40 band mismatch. Preserve full RF/matching/ESD/antenna keepout budget.
5. TPA2016D2/BS08 are audio test candidates. Default-off hardware control plus independent limiter/fault containment required; programmable AGC alone cannot close the hardware safety gate.
6. Select capacity from measured consumption and requested runtime. Existing500mAh cell is reference only; explicitly model larger packs and wearability conflict. All rails, charger default settings, protection, NTC, fuel gauge and connectors need qualification.
7. Produce separate RevG CAD and KiCad. Native review artifacts must distinguish real circuits from open module interfaces, and component dimensions from guessed solution envelopes. A placement-only PCB is not routed/released. Full mainboard completion is blocked where interfaces remain unverified; report gaps rather than fabricating a successful ERC/DRC.
8. Preserve all older files byte-for-byte. No production Gerbers, purchases, firmware flashing or physical test claims in this work.

## Ownership

- Root: system assumptions, change plan, cost scenarios, failure/latency contracts, test plan, final review/package.
- Electronics workstream: only electronics/**, BOM.csv, docs/ELECTRONICS_REVIEW.md.
- Mechanical workstream: only mechanical/**, previews/**, docs/MECHANICAL_REVIEW.md.
- Cross-domain interfaces communicated before implementation; no concurrent editing of same file.

## Requirements confirmed by user during this work

Egypt; unlocked compatible SIM, no exclusive operator, test at least TWO operators at the trial site selected by measured coverage. Build10–20 engineering validation units BEFORE100-device pilot. Retail targetEGP12000–18000. Minimum2h full continuous operation, goal4h typical use with declared duty cycle. Total worn mass target<=60g;70g upper boundary requires justification and wear testing. Physical capture-to-bone-output p95<=150ms; if p95>200ms the experience must NOT be described as live listening before architecture/function reevaluation. Report p50/p95/p99 and losses, not successful packets only. Cost at100 includes components, assembly, shipping, tax assumptions and test; data/cloud recurring costs separate. These supersede preliminary scenario targets. No measured compliance established.

## Major risks and validation order

| Risk | Required evidence before freeze |
|---|---|
| Selected visible face not matched to correct audio | Calibrated camera/mic geometry, confidence/no-target tests, overlapping/offscreen trials |
| Four mic channels silently mixed or skewed | Raw four-channel capture, channel map, shared clock and phase calibration |
| USB host/hub concurrency/recovery unsupported | Intended purchased silicon+SDK+camera+modem simultaneous stress/fault test |
| LTE/cloud cannot satisfy delay | Physical capture-to-transducer latency distribution on chosen operators, not modem bitrate |
| Battery duration incompatible with mass/heat | Measured average/peak power then pack selection, thermal/current tests |
| Audio limiter fails or depends only on software | Electrical fault injection/dummy-load thresholds approved before worn tests |
| Folding/cabling clashes | New static and full-angle sampled CAD tests; physical cycle/routing verification |
| Price target unrealistic | Quantity-specific quotes plus NRE, yield, import, distribution, data/cloud recurring costs |

Execution order: publish this plan -> primary-source component/architecture review -> native subsystem/interface schematic -> PCB design-stage artifact -> revised packaging and collision tests -> archived ERC/DRC and review -> test/cost/gap reports -> checked handoff package. No claim of closing physical gates without instruments and parts.
