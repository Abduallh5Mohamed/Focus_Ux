"""FOCUS RevD industrial-design engineering review. Actual maker STEP is included.
This is CAD form review, not production/clinical/wearability qualification.
"""
from pathlib import Path
import json,math,shutil
import FreeCAD as A,Part,Mesh,Sketcher
ROOT=Path('A:/Focus_Ux/hardware_revD');OUT=ROOT/'mechanical';OUT.mkdir(exist_ok=True,parents=True)
(ROOT/'previews').mkdir(exist_ok=True);(ROOT/'docs').mkdir(exist_ok=True)
doc=A.newDocument('FOCUS_RevD_Industrial_Review')
V=A.Vector
def box(x,y,z,dx,dy,dz):return Part.makeBox(dx,dy,dz,V(x,y,z))
def cyl(r,h,x,y,z,axis=(0,0,1)):return Part.makeCylinder(r,h,V(x,y,z),V(*axis))
def rr(w,h,t,r,cx,y,cz):
 s=box(-w/2+r,-h/2,0,w-2*r,h,t).fuse(box(-w/2,-h/2+r,0,w,h-2*r,t))
 for a in [-1,1]:
  for b in [-1,1]:s=s.fuse(cyl(r,t,a*(w/2-r),b*(h/2-r),0))
 s=s.removeSplitter();s.rotate(V(),V(1,0,0),90);s.translate(V(cx,y+t,cz));return s
def profile(cx,y,cz,w,h,r):
 # Cross-section from smooth rectangle solid on XZ; extract front perimeter.
 s=rr(w,h,.1,r,cx,y,cz)
 faces=[f for f in s.Faces if abs(f.CenterOfMass.y-y)<1e-5 and f.Area>w*h*.45]
 return max(faces,key=lambda f:f.Area).OuterWire
def safe_fillet(s,r,selector=None):
 try:
  ed=[e for e in s.Edges if selector is None or selector(e)]
  n=s.makeFillet(r,ed)
  if n.isValid() and len(n.Solids)==1:return n
 except Exception:pass
 return s
parts=[];refs=[];surfaces=[];notes=[]
def add(n,s,group='part',note=''):
 o=doc.addObject('Part::Feature',n);o.Label=n.replace('_',' ');o.Shape=s.removeSplitter()
 o.addProperty('App::PropertyString','EngineeringStatus','FOCUS');o.EngineeringStatus=note
 {'part':parts,'ref':refs,'surface':surfaces}[group].append(o);return o

# Actual manufacturer source. Rx180 transforms camera direction+Y into forward-Y.
source=ROOT/'reference/Seeed Studio XIAO-ESP32-S3-Sense.step'
module=Part.read(str(source))
module.rotate(V(),V(1,0,0),180);module.translate(V(63.75,.25,10.25))
assert module.isValid()
add('Manufacturer_Sense_Assembly',module,'ref','Imported official maker CAD, old camera revision; must match purchased sample. No fake internals. Contains103 solids, no physical verification.')

# Main frame. Lens regions are parameterized datum sketches for optician review;
# final prescription lens edge/retention requires lab fitting, not represented here.
front=None
for x in [-30,30]:
 outer=rr(57,42,5,11,x,0,0)
 inner=rr(47,32,8,8,x,-1,0)
 ring=outer.cut(inner)
 front=ring if front is None else front.fuse(ring)
front=front.fuse(rr(17,9,5,3,0,0,11.5))
front=front.fuse(rr(139,8,5,3,-1,0,18))
front=front.fuse(rr(15,15,5,5,-65,0,14))
front=safe_fillet(front,.65,lambda e:e.Length>2)

# Integrated tapered right capture wing: smooth XZ rounded cross-sections.
outer=Part.makeLoft([
 profile(72.5,-15.4,17,18,18,5.5),
 profile(68.5,-9,17,27.5,22.5,5.5),
 profile(66.5,3,16,32,25,6)
],True,False)
assert outer.isValid()
# Use conservative individual maker-component AABBs (+0.6mm clearance) for service cavity.
# This avoids inventing a tiny internal board and preserves actual protrusions.
cavities=[]
for s in module.Solids:
 b=s.BoundBox
 cavities.append(box(b.XMin-.6,b.YMin-.6,b.ZMin-.6,b.XLength+1.2,b.YLength+1.2,b.ZLength+1.2))
cut=Part.makeCompound(cavities)
housing=outer.cut(cut)
# Open optics around actual camera lens boundingbox; cosmetic bezel is not a glass spec.
housing=housing.cut(cyl(5.1,15,72.5,-18,17,(0,1,0)))
# Service lid removal area at back; do not trap the module into a closed monolithic body.
housing=housing.cut(rr(28,21,6,4,66.5,1.5,16))
# USB access based on actual module CAD connector envelope; plug remains procurement-dependent.
housing=housing.cut(box(75,-5.5,11,10,7,11))
# Broad union overlap at front rim joins housing to frame. Remove module keepouts again.
front=front.fuse(housing).cut(cut)
# Left/right hidden-axis temple lugs; bores along Z for M2.5 prototype shoulder hardware.
for x in [-68,73]:
 lug=rr(11,13,8,3.5,x,18,15)
 # connecting support, outside lens regions
 link=box(x-4,3,19,8,23,4)
 front=front.fuse(lug).fuse(link)
 front=front.cut(cyl(1.35,20,x,24,5))
front=front.removeSplitter()
add('Front_Capture_Chassis',front,note='Integrated rounded/tapered capture wing around real maker geometry. Lens edging/retention, mic apertures, antenna routing and purchased revision unresolved. NOT manufacturing frozen.')

# Back service door, gap0.35. Hidden M1.6 ears belong outside component envelope.
door=rr(27.3,20.3,1.5,3.6,66.5,3.35,16)
# Service openings avoid guessed camera/microphone blocking and allow cable access.
door=door.cut(box(74.5,2,11,7,5,11))
for z in [9,23]:
 # A small tooling/retention aperture: exact screws only after module fit test.
 door=door.cut(cyl(.9,4,55,2,z,(0,1,0)))
add('Right_Service_Door',door,note='Prototype service door; fastener engagement and IP sealing are open engineering items. Snap/adhesive fixation NOT silently assumed.')
# Carry the service opening through the complete front union, including the rim/lugs.
front=front.cut(rr(28,21,6,4,66.5,1.5,16)).removeSplitter()
# Structural rear hinge yoke bypasses the service opening instead of leaving a floating lug.
yoke=box(49,4,19,3.2,11,4).fuse(box(49,11,19,29.5,4,4))
front=front.fuse(yoke).removeSplitter()
parts[0].Shape=front

# Temples: smooth varying ellipsoidal sections for thicker electronics-side front,
# taper to soft ear tips; no decorative dummy battery volumes.
def ellipse_wire(x,y,z,rx,rz):
 pts=[V(x+rx*math.cos(t),y,z+rz*math.sin(t)) for t in [i*2*math.pi/32 for i in range(32)]]
 c=Part.BSplineCurve();c.interpolate(pts,PeriodicFlag=True);return Part.Wire(c.toShape())
for sign,x in [(-1,-68),(1,73)]:
 name='Left' if sign<0 else 'Right'
 arm=Part.makeLoft([ellipse_wire(x,36,16,4.3,6),ellipse_wire(x+sign*.8,45,17,4.6,5.4),ellipse_wire(x+sign*1.6,78,16,3.4,4.4),ellipse_wire(x+sign*1.4,112,13,2.9,3.7),ellipse_wire(x+sign*.2,137,4,2.7,3.2)],True,False)
 # Pivot eye is stepped above front lug; connected by a short joint neck.
 eye=cyl(4.4,3,x,24,23.3)
 neck=box(x-3.5,23,23.3,7,19,3).fuse(box(x-3.5,37,16,7,5,10.3))
 arm=arm.fuse(eye).fuse(neck).cut(cyl(1.35,8,x,24,21))
 # Hinge lug may touch only at designed faces; avoid static print interference.
 # Recess the lens-side underside above the front lug.
 arm=arm.cut(box(x-6,17,5,12,13.8,18.1))
 # Internal relief volume only; a continuous cable path through hinge is not yet validated.
 channel=Part.makeLoft([ellipse_wire(x+sign*.5,43,16,1.4,2.2),ellipse_wire(x+sign*1.5,72,15.8,1.4,2.2),ellipse_wire(x+sign*1.4,99,14.5,1.4,2.2)],True,False)
 arm=arm.cut(channel)
 arm=arm.cut(front).cut(door).removeSplitter()
 for yy in [47.5,74]:arm=arm.cut(cyl(.9,20,x-10,yy,16,(1,0,0)))
 add(name+'_Temples',arm,note='Smoothed loft with internal routing channel and provisional hinge. Fit, flex, cable bend radii and strength not yet measured. No battery or antenna certified by this void.')
 # Separate soft-end overmould shown as removable sleeve, not claimed material.
 sleeve=Part.makeLoft([ellipse_wire(x+sign*1.4,112,13,3.35,4.2),ellipse_wire(x+sign*.2,137,4,3.15,3.7),ellipse_wire(x-sign*.2,143,2,2.5,3.1)],True,False)
 sleeve=sleeve.cut(arm)
 add(name+'_Ear_Sleeve',sleeve,note='Concept soft sleeve; final skin-contact material/durometer/retention not selected.')

# Bone-conduction bench packaging. ONLY supplier bounding envelopes, no invented internals.
# Adafruit1674: product14x21.5mm; linked C2049 datasheet7.9mm depth.
# Place inner-face normal along X. No contact-face/pressure claim without purchased sample.
for sign,x in [(-1,-68),(1,73)]:
 name='Left' if sign<0 else 'Right'
 # Build left cradle locally; mirror it for right side by coordinate transformation.
 bx=-64.4; yy=50; zz=9
 body=box(bx,yy,zz,7.9,21.5,14)
 shell=box(-66.2,47.5,6.5,10.4,26.5,19)
 # Pocket and fully open nominal skin-facing side, leaving no claimed diaphragm dimensions.
 shell=shell.cut(box(bx-.25,yy-.25,zz-.25,12,22,14.5))
 # Provisional2.8mm rear wire exit; actual terminal position/strain relief need sample.
 shell=shell.cut(cyl(1.4,7,-60.5,71.5,11,(0,1,0)))
 # Rear clamp plate and screw ears bridge into temple; separate removable printed part.
 shell=shell.fuse(box(-66.2,45.8,13,3.4,3.7,6)).fuse(box(-66.2,72.5,13,3.4,3.3,6))
 for cy in [47.5,74]:shell=shell.cut(cyl(.9,19,-75,cy,16,(1,0,0)))
 cap=box(-55.8,47.5,6.5,.8,26.5,19).fuse(box(-56.5,50,9,.7,21.5,14))
 for cy in [48.75,72.75]:
  bore=cyl(.65,15,-68,cy,20,(1,0,0))
  shell=shell.cut(bore);cap=cap.cut(bore)
 if sign>0:
  # Proper rigid180 rotation aboutY flips X andZ, keeping upright viaZtranslation32.
  # Reflecting onlyX is intended geometrical mirror here, not STEP import orientation.
  m=A.Matrix();m.A11=-1;m.A14=5
  body=body.transformGeometry(m);shell=shell.transformGeometry(m);cap=cap.transformGeometry(m)
 arm=doc.getObject(name+'_Temples').Shape
 keepout=box(-76,34,9.5,11.8,67,13.5)
 if sign>0:keepout=keepout.transformGeometry(m)
 shell=shell.cut(keepout).removeSplitter()
 add(name+'_BC_Cradle',shell,note='Removable screw-clamp cradle around published1674 envelope. Clamp hardware, isolation and contact preload require bench fit; no skin-safe material selected.')
 add(name+'_BC_Contact_Cover',cap,note='Separate0.8mm provisional insulating capture plate plus0.7mm nominal face-contact boss closes outward escape if two M1.2 fasteners are fitted. Contact face is ASSUMED from envelope, no established preload. Material, thread engagement, vibration transfer and pressure are UNTESTED. Not a qualified skin-contact surface.')
 add(name+'_BC_Transducer_Envelope',body,'ref','Adafruit1674 bounding box ONLY:7.9x21.5x14mm,9.6g; contact face must be checked on sample. Not manufacturer internal CAD.8ohm1W product spec conflicts with linked supplier PDF, verify sample.')

# Optical inserts are reference surfaces only, removable to inspect frame apertures.
for x,name in [(-30,'Left'),(30,'Right')]:
 lens=rr(46.6,31.6,1.4,7.8,x,1.5,0)
 add(name+'_Lens_Reference',lens,'surface','Flat optical placeholder only. No prescription, optical performance, impact rating or lens retention claim.')

# Nose interface placeholders, distinctly documented; these are softer-style geometry.
for sign in [-1,1]:
 mat=A.Matrix();mat.A11=3.8;mat.A22=2.5;mat.A33=6.5
 pad=Part.makeSphere(1).transformGeometry(mat);pad.translate(V(sign*8,4,-2))
 add(('Left' if sign<0 else 'Right')+'_Nose_Pad_Reference',pad,'surface','Nose support envelope; user fit and attachment mechanism must be engineered before wear.')

# Transparent aperture reference sketches: source-controlled design datums, not proof of fitted lenses.
sk=doc.addObject('Sketcher::SketchObject','Lens_Opening_Datums')
sk.Label='Lens opening datum - 47 x 32 mm'
for cx in [-30,30]:
 for a,b in [((cx-23.5,-16),(cx+23.5,-16)),((cx+23.5,-16),(cx+23.5,16)),((cx+23.5,16),(cx-23.5,16)),((cx-23.5,16),(cx-23.5,-16))]:
  idx=sk.addGeometry(Part.LineSegment(V(*a,0) if False else V(a[0],a[1],0),V(b[0],b[1],0)),True)
  sk.addConstraint(Sketcher.Constraint('Block',idx))
sk.Placement=A.Placement(V(0,0,0),A.Rotation(V(1,0,0),90))

doc.addObject('App::DocumentObjectGroup','Mechanical_Review_Parts').addObjects(parts)
doc.addObject('App::DocumentObjectGroup','Actual_Hardware_Reference').addObjects(refs)
doc.addObject('App::DocumentObjectGroup','Optical_And_Fit_References').addObjects(surfaces)
print("built all features",flush=True)
doc.recompute()
print("validating topology",flush=True)
invalid=[]
for o in parts:
 if not o.Shape.isValid() or len(o.Shape.Solids)!=1:invalid.append([o.Name,o.Shape.isValid(),len(o.Shape.Solids)])
assert not invalid,invalid
print("checking module clearance",flush=True)
hits=[]
for o in parts:
 v=o.Shape.common(module).Volume
 if v>.05:hits.append([o.Name,round(v,4)])
assert not hits,hits
print("checking static part pairs",flush=True)
intersections=[]
for i,o in enumerate(parts):
 for p in parts[i+1:]:
  print(o.Name,p.Name,flush=True)
  v=o.Shape.common(p.Shape).Volume
  if v>.05:intersections.append([o.Name,p.Name,round(v,4)])
assert not intersections,intersections
print("saving native CAD",flush=True)
doc.saveAs(str(OUT/'FOCUS_RevD_Industrial_Review.FCStd'))
Part.export(parts+refs+surfaces,str(OUT/'FOCUS_RevD_Assembly.step'))
(OUT/'stl').mkdir(exist_ok=True)
for o in parts:Mesh.export([o],str(OUT/'stl'/(o.Name+'.stl')))
report={'revision':'D - wired bone conduction bench packaging, not production release',
 'manufacturer_model_solids':len(module.Solids),'hardware_transform':'Rx180 then translation(63.75,.25,10.25)',
 'parts':[{'name':o.Name,'valid':o.Shape.isValid(),'solids':len(o.Shape.Solids),'volume_mm3':round(o.Shape.Volume,2)} for o in parts],
 'hardware_intersections_mm3':hits,'static_print_intersections_mm3':intersections,
 'open_items':['camera revision match','mic acoustic aperture confirmation','antenna position and RF keepout','USB cable and power source','nose pad and hinge retention','wearability/strength/heat','capture sync and realtime latency','actual manufacture and assembly tests']}
(OUT/'validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
shutil.copy2(Path(__file__),OUT/'build_revd.py')
print(json.dumps(report,indent=2))
