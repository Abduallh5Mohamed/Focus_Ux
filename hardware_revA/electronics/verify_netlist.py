"""Compare exported KiCad schematic connectivity to routed board, ignoring NC pins."""
from pathlib import Path
import xml.etree.ElementTree as ET, json, pcbnew as p
r=Path(__file__).resolve().parent
sch={n.attrib['name'].lstrip('/'):{(x.attrib['ref'],x.attrib['pin']) for x in n.findall('node')} for n in ET.parse(r/'schematic.net.xml').findall('.//nets/net') if not n.attrib['name'].lstrip('/').startswith('unconnected-')}
b=p.LoadBoard(str(r/'focus_control.kicad_pcb')); pcb={}
for f in b.GetFootprints():
 for pad in f.Pads():
  if pad.GetNetname() and not pad.GetNetname().startswith('unconnected-'):pcb.setdefault(pad.GetNetname().lstrip('/'),set()).add((f.GetReference(),pad.GetNumber()))
assert sch==pcb,(sch,pcb)
assert len(sch)==5
out={'result':'PASS','connected_nets':{n:sorted(list(v)) for n,v in sch.items()},'comparison':'Exact connected-net pad membership equality after normalizing root-sheet leading slash; intentionally NC pins ignored.','note':'This is not KiCad schematic-parity DRC; mounting holes are board-only mechanical footprints.'}
(r/'connectivity_check.json').write_text(json.dumps(out,indent=2))
print('PASS: 5 connected schematic nets exactly match PCB pad membership')
