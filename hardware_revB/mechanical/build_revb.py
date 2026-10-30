"""Rev B packaging feasibility: tiny camera+mic+WiFi candidate, phone gateway.
No RF PCB, antenna placement, charging design or wearable certification is implied.
"""
from pathlib import Path
import FreeCAD as A,Part,Mesh,json,shutil
root=Path('A:/Focus_Ux/hardware_revB');out=root/'mechanical'
out.mkdir(parents=True,exist_ok=True);(root/'previews').mkdir(exist_ok=True)
doc=A.newDocument('FOCUS_RevB_Clip')
def box(x,y,z,w,d,h):return Part.makeBox(w,d,h,A.Vector(x,y,z))
def cy(r,h,x,y,z,axis=(0,0,1)):return Part.makeCylinder(r,h,A.Vector(x,y,z),A.Vector(*axis))
def rounded(w,h,t,r,cx,y,cz):
 s=box(-w/2+r,-h/2,0,w-2*r,h,t).fuse(box(-w/2,-h/2+r,0,w,h-2*r,t))
 for i in [-1,1]:
  for j in [-1,1]:s=s.fuse(cy(r,t,i*(w/2-r),j*(h/2-r),0))
 s=s.removeSplitter();s.rotate(A.Vector(),A.Vector(1,0,0),90);s.translate(A.Vector(cx,y+t,cz));return s
parts=[];refs=[]
def add(n,s,ref=False,note=''):
 o=doc.addObject('Part::Feature',n);o.Shape=s.removeSplitter();o.Label=n.replace('_',' ')
 o.addProperty('App::PropertyString','Status','FOCUS');o.Status=note
 (refs if ref else parts).append(o);return o

# Context is an illustrative ordinary frame, not a new prescription frame design.
front=None
for x in [-34,34]:
 s=rounded(58,42,3,12,x,0,0).cut(rounded(52,36,5,9,x,-1,0))
 front=s if front is None else front.fuse(s)
front=front.fuse(rounded(14,6,3,2,0,0,12))
for x in [-70,70]:front=front.fuse(box(x-2.5,0,12,5,133,6)).fuse(box(min(x,61 if x>0 else -70),0,12,9,3,6))
add('CONTEXT_Existing_Eyeglasses',front,True,'Illustrative frame only. Existing prescription eyewear dimensions and clearance vary. Do not print as optical eyewear.')

# Published candidate family: XIAO ESP32-S3 Sense21x17.8x15mm (revision-dependent).
# Normal direction faces front (-Y); actual optical centre/ports/antenna unknown.
module=box(78,-13.5,7.6,21,15,17.8)
add('REFERENCE_Sense_Module_Envelope',module,True,'Manufacturer family envelope21x17.8x15mm. Camera revision, lens centre, mic, antenna and power connector positions unverified. Not a manufacturer STEP.')

# Open-front review cradle. No final apertures/antenna keepout invented.
body=box(76.5,-15,6,24,18,21).cut(box(77.5,-16,7,22,17.5,19))
# Rear is open for service, closes with removable lid; mounting strap slots.
body=body.cut(box(78,1,7.5,21,4,18))
for x in [76,99]:body=body.cut(box(x,-8,12,2,4,8))
# Clip-on U bracket: body connects over the external upper temple.
bracket=box(64.5,10,12,13.5,16,11).cut(box(67,9,11,6,18,9))
body=body.fuse(bracket).fuse(box(74,2,20,6.5,24,3))
# Jaw bolts are provisional M1.6. Clamp gap6mm serves a nominal5mm temple + liner.
for x in [65.8,76.5]:body=body.cut(cy(.65,18,x,18,9))
add('Clip_Cradle',body,note='PACKAGING STUDY. Open face avoids guessed optical/acoustic apertures. Printed clamp needs actual eyewear/liner/fastener tests; retention not validated.')
lid=box(76.5,3.4,6,24,1.5,21)
lid=lid.cut(box(76,3,19.8,5,3,3.4))
for x in [79,96]:lid=lid.cut(box(x,2.5,12,2,4,8))
add('Rear_Service_Lid',lid,note='Packaging study; retained by review straps, not a finalized snapfit. Connector/cable exits deferred until sample measured.')
jaw=box(64.5,10,9.6,13.5,16,2)
for x in [65.8,76.5]:jaw=jaw.cut(cy(.9,4,x,18,8.5))
add('Lower_Clamp_Jaw',jaw,note='Nominal6mm clamp width for reference5mm temple with soft liner. Tightening torque and stress not validated.')

doc.addObject('App::DocumentObjectGroup','Prototype_Clip_Parts').addObjects(parts)
doc.addObject('App::DocumentObjectGroup','Reference_Context').addObjects(refs)
doc.recompute()
assert all(o.Shape.isValid() and len(o.Shape.Solids)==1 for o in parts)
collisions=[]
for i,a in enumerate(parts):
 for b in parts[i+1:]:
  v=a.Shape.common(b.Shape).Volume
  if v>.01:collisions.append([a.Name,b.Name,round(v,4)])
assert not collisions,collisions
module_hits=[]
for p in parts:
 v=p.Shape.common(module).Volume
 if v>.01:module_hits.append([p.Name,round(v,3)])
assert not module_hits,module_hits
doc.saveAs(str(out/'FOCUS_RevB_Clip_Packaging.FCStd'))
Part.export(parts+refs,str(out/'FOCUS_RevB_Clip_Packaging.step'))
(out/'stl').mkdir(exist_ok=True)
for o in parts:Mesh.export([o],str(out/'stl'/(o.Name+'.stl')))
report={'revision':'B - packaging feasibility only','module_candidate_mm':[21,17.8,15],
 'cradle_body_mm':[24,18,21],'complete_clip_extents_mm':[36,41,21],
 'prototype_parts':len(parts),'valid_single_solids':True,'print_part_intersections':collisions,
 'module_envelope_intersections':module_hits,
 'unverified':['simultaneous A/V capture+WiFi throughput and timestamps','actual module revision and connector/antenna layout','framefit and retention','weight, comfort and heat','battery/charging and mobile gateway','lowlatency extraction and returned audio'],
 'notice':'Geometry checks only; no electrical or wearable proof. No custom RevB PCB or firmware delivered.'}
(out/'validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
shutil.copy2(Path(__file__),out/'build_revb.py')
print(json.dumps(report,indent=2))
