# RevG requirements, assumptions and open issues

Date2026-10-30. Tags: USER=confirmed requirement; SOURCE=published evidence; DESIGN=proposed decision; ASSUMPTION=calculation input only; UNTESTED=no physical result.

## Confirmed requirements

| ID | Requirement | Current result |
|---|---|---|
| R01 | Egypt; retail targetEGP12000–18000 | USER; no finalized selling price |
| R02 | 10–20 engineering units then100 pilot | USER; no parts ordered/assembled |
| R03 | Unlocked SIM; >=2 operators selected by coverage | USER; operator/SKU/bands unverified |
| R04 | >=2h FULL continuous operation | USER; UNTESTED; pack sizing unresolved |
| R05 | >=4h typical usage | USER; duty-cycle profile requires agreement and measurement |
| R06 | <=60g target total worn mass | USER; estimate not physical weigh-in |
| R07 | 70g upper bound needs justification/wear trial | USER; not automatic relaxation |
| R08 | capture-to-bone-output p95<=150ms | USER; UNTESTED |
| R09 | p95>200ms excludes live-listening claim pending reevaluation | USER; no moving threshold |
| R10 | User selects visible person without forced isolated voice registration | USER prior steering; robust association unproven |
| R11 | Dedicated onboard battery/LTE/Nano-SIM, no phone gateway | USER; existing RevE did not implement this |
| R12 | Cost/unit100 includes assembly/shipping/tax/test; data/server separate | USER; provisional financial assumptions clearly tagged |

## Assumptions allowed for sensitivity analysis only

Nominal1S3.7V; usable energy factor0.70 for combined conversion/reserve/aging/load uncertainty; this is NOT measured. Continuous whole-system battery-equivalent demand scenarios1/2/4/6W. Typical4h examples with25%/50%/75% active duty and separately specified idle draw. These are scenario inputs, not predictions that LTE can sleep during live listening. Live capture/uplink/inference remains full active regardless of speaker silence unless demonstrated duty cycling preserves function.

FX scenarios45/55/65EGP per USD, not current FX quotes. Import burden/VAT and margins are model parameters, not tax/legal advice or confirmed classification. Obtain Egyptian customs/classification and supplier quotations before orders. No clinical safety thresholds are inferred from power ratings, a CAD gap, a temperature target or an algorithmic latency.

## Open engineering decisions and closure evidence

| Issue | Owner needed | Closure |
|---|---|---|
| Host SKU/silicon revision/SDK and full peripherals | Embedded lead | Purchased board ID, pinned SDK, sustained simultaneous capture/network/playback plus USB recovery logs |
| Four-channel capture | Audio/embedded | Independent raw channels, common clock, channel map/skew and no silent summing |
| Camera SKU/modes/FoV/current | Vision/embedded | Sample enumeration, sync/rolling-shutter behavior, association at working distances |
| Mic cheaper equivalent | Audio/procurement | Active lifecycle, price quote, sensitivity/phase/port/voltage/package verified; calibrate array |
| A7670E full SKU and bands | RF/operator | Manufacturer manual for purchased module; actual two-operator attachment/latency at location |
| Antenna full-band suitability | RF | Correct part/drawing, assembled VNA and OTA/head-loaded performance; prior FXP40 discrepancy resolved |
| Battery capacity/package | Power/pack vendor |2h active power trace, safety margins, supplier protected-pack drawing, qualified harness/connector/NTC |
| Charge/fuel gauge settings | Power/firmware | Datasheet-matched cell, reset/watchdog/NTC/low-voltage tests |
| Independent limiter | Audio safety engineer | Analog/electrical maximum threshold and hardware inhibition verified under MCU/I2C faults |
| BS08 identity/contact mechanics | Audio/mechanical | Supplier controlled drawing, measured impedance/transfer/force and insulation |
| Full mainboard schematic/routing | Electrical/RF | Complete verified subsystem connections, review, stackup/layout/routing/DFM then bench evidence |
| Wearable mass/CG/fit/folding | Mechanical | All actual parts weighed, native CAD checks including harness, physical mockup and wear/cycle tests |
| Model/association performance | ML/audio/vision | Held-out room tests, no identity switch, fail-uncertain behavior |
| Live LTE feasibility | Integration | Physical latency p50/p95/p99, stalls/losses and two-operator repeated trials |
| Production cost | Procurement/manufacturer |10/20/100/500/1000 quotes, NRE/tooling/test/yield/import/support allocation |

Requested FOCUS_Expert_Review_AR.md was absent from project and supplied attachment search; no content inferred. All previous hardware claims are bounded by source records. No final PCB or battery drawing can be honestly frozen from missing measurements. Current delivery is an engineering development package with explicit completeness matrix.
