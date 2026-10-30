# Verification and open engineering gates

## Observed
Native FreeCAD generation and STEP/STL export executed using installed FreeCAD1.1.1. Native views rendered with FreeCADGui and inspected. Six print parts pass BRep validity and single-solid checks; no positive-volume intersection between print parts in the open configuration. Bare KiCad board imported using a proper rotation, not a reflection.

KiCad10.0.7 native project/schematic/PCB saved. CLI ERC/DRC/parity checks and connected-pad comparison independently recorded. Carrier has no 5V input on its headers and routes only GPIO/control nets. USB power and data stay on Pico module. Pico module internals are not verified by carrier ERC.

## Not established
- Complete audio/video hardware design: UVC module is an external purchased subsystem, not designed here.
- Optical sensor centre/microphone/connector locations or camera screw pattern: only outer envelope sourced.
- Powered electrical operation, Pico orientation on purchased sockets, connector MPN compatibility and actual assembled height.
- Camera retention, facial fit, balance, nose padding, hinge retention/wear, sweat/drop strength, FEA, material safety or manufacturing tolerances.
- Media timestamp synchronization, stream modes on the purchased variant, latency, throughput, audio quality, user comprehension or clinical benefit.
- USB aggregate current including camera, controller, headset and hub. Manufacturer camera180mA at5V is a component nominal datum, not total system power. Battery life cannot be claimed: no battery design exists.
- Exact commercial module rights/model-weights permissions for a final product are separate release questions.

## Stop gates before ordering production
Finalize BOM and verify drawings; inspect/meter first PCB; test USB/GPIO/firmware; camera+mic enumeration; timestamp/sync and per-target GPU parity; cable/plug/mechanical assembly; fit/comfort/temperature/current; fault/disconnect/mute behavior; manufacturer DFM/DFA and jurisdiction/claims review. No numerical pass values for clinical suitability have been invented.
