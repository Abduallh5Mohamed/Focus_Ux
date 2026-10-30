# Physical orientation release check — corrected USB-left pin rows

Independent root review caught an error in the initial draft: J1 (physical Pico pins1..20) was initially placed on the top row although the USB connector pointed left. That mirrored the physical module pin layout. The error was corrected in the actual PCB placement and routing, not only in documentation. All fabrication/STEP/preview outputs were regenerated afterward.

## Reference

- [Official original Pico pinout PDF](https://datasheets.raspberrypi.com/pico/Pico-R3-A4-Pinout.pdf): component-side view, USB at top, physical1 top-left, physical20 bottom-left, physical40 top-right, physical21 bottom-right.
- Installed KiCad10 footprint: `A:/Kicad/share/kicad/footprints/Module.pretty/RaspberryPi_Pico_Common_THT.kicad_mod`. In its initial orientation, pin1(0,0), pin20(0,48.26), pin40(17.78,0), pin21(17.78,48.26)mm. This agrees with the official numbering diagram.

## Coordinate transformation

KiCad board top view has X right,Y down. Rotating the reference footprint +90degrees applies `(x,y)->(y,-x)`. Translate by `(8.37,24.89)`mm:

`carrierX = 8.37 + originalY`

`carrierY = 24.89 - originalX`

The module's USB top edge therefore becomes the left edge. The physical left row becomes the carrier's **bottom** row. This is a rotation, not a reflection.

| Physical Pico pin | Carrier coordinate mm | Carrier socket |
|---|---|---|
| 1 GP0 | (8.37,24.89) | J1.1 |
| 3 GND | (13.45,24.89) | J1.3 |
| 4 GP2 select | (15.99,24.89) | J1.4 |
| 5 GP3 stop | (18.53,24.89) | J1.5 |
| 6 GP4 LED | (21.07,24.89) | J1.6 |
| 20 GP15 | (56.63,24.89) | J1.20 |
| 40 VBUS | (8.37,7.11) | J2.1 |
| 21 GP16 | (56.63,7.11) | J2.20 |

The generator independently loads this stock reference footprint, rotates/translates it and asserts **every40 socket-pad coordinate** equals its corresponding physical Pico pin. Output: `physical_orientation_check.json`, PASS40/40.

Electrical logic is unchanged: physical4/5/6/3 for GP2/GP3/GP4/GND. Actual pad positions and tracks were moved/rebuilt to match the physical module. New routing has no vias. Check3 ground and40 VBUS with an unpowered real Pico H before first power; no physical assembly has been performed yet.

Post-correction ERC0, DRC0, schematic-parity0, custom connectivity5/5 all passed. This demonstrates why logical netlist checks alone cannot establish physical pin orientation.

## STEP coordinate verification

FreeCAD imported the final generic populated STEP and reported the LED solid bounding box X1.1..4.9,Y-11.17..-7.77mm. Socket rows appear at negative Y ranges-8.38..-5.84 and-26.16..-23.62mm. Raw STEP therefore represents KiCad positive boardY as negative STEP_Y. For board coordinates `(u,v)`, use `u=STEP_X,v=-STEP_Y`. For the parent pod mapping `globalX=115-v,globalY=30+u`, the correct raw STEP mapping is `globalX=115+STEP_Y,globalY=30+STEP_X`. The bare board dielectric solid is65x32x1.51mm; nominal finished-board thickness is1.6mm. Generic connector tails reachZ-1.505mm below board origin; reserve underside clearance.
