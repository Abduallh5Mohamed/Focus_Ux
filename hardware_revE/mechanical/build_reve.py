"""RevE wearability architecture study. New components, not a scaled RevD assembly.
Native CAD packaging/form proposal; no physical comfort/manufacture qualification.
"""
from pathlib import Path
import math,json,shutil
import FreeCAD as A,Part,Mesh
V=A.Vector
root=Path('A:/Focus_Ux/hardware_revE');out=root/'mechanical'
for p in [out,root/'previews',root/'docs',root/'reference']:p.mkdir(parents=True,exist_ok=True)
doc=A.newDocument('FOCUS_RevE_Wearability_Study')
parts=[];refs=[];fit=[]
def box(x,y,z,a,b,c):return Part.makeBox(a,b,c,V(x,y,z))
def cyl(r,h,x,y,z,axis=(0,0,1)):return Part.makeCylinder(r,h,V(x,y,z),V(*axis))
def rr(w,h,t,r,cx,y,cz):
 s=box(-w/2+r,-h/2,0,w-2*r,h,t).fuse(box(-w/2,-h/2+r,0,w,h-2*r,t))
 for a in [-1,1]:
  for b in [-1,1]:s=s.fuse(cyl(r,t,a*(w/2-r),b*(h/2-r),0))
 s=s.removeSplitter();s.rotate(V(),V(1,0,0),90);s.translate(V(cx,y+t,cz));return s
def yzround(w,h,t,r,x,cy,cz):
 s=rr(w,h,t,r,0,0,0);s.rotate(V(),V(0,0,1),-90);s.translate(V(x,cy,cz));return s
def ellipse(x,y,z,rx,rz):
 c=Part.BSplineCurve();c.interpolate([V(x+rx*math.cos(i*2*math.pi/24),y,z+rz*math.sin(i*2*math.pi/24)) for i in range(24)],PeriodicFlag=True)
 return Part.Wire(c.toShape())
def add(n,s,group='part',note=''):
 o=doc.addObject('Part::Feature',n);o.Label=n.replace('_',' ');o.Shape=s.removeSplitter()
 o.addProperty('App::PropertyString','EvidenceBoundary','FOCUS');o.EvidenceBoundary=note
 {'part':parts,'ref':refs,'fit':fit}[group].append(o)
 print(n,o.Shape.isValid(),len(o.Shape.Solids),flush=True);return o
def mirror(s):
 m=A.Matrix();m.A11=-1;return s.transformGeometry(m)

# Narrow rims and a continuous brow; no development board in the frame.
front=None
for x in [-31.5,31.5]:
 s=rr(55,39.8,3.2,10.7,x,0,0).cut(rr(50.8,35.6,6,9,x,-1,0))
 front=s if front is None else front.fuse(s)
front=front.fuse(rr(15.5,5.5,3.2,2,0,0,12.4))
front=front.fuse(rr(144,5.8,3.5,2.4,0,-.2,18.7))
for x in [-70.5,70.5]:front=front.fuse(rr(11.5,11,3.5,3.5,x,-.2,16))
# Arducam-authored B0441 datasheet p3:62x9x6mm, single microphone, USB2UVC.
# A long horizontal board fits a brow instead of a lateral box.0.4mm nominal pocket.
# Lens centre is a nominal registration target pending controlled lens/connector3D data.
cam=box(-31,-5.2,15,62,6,9)
housing=rr(65.2,12,9,3.2,0,-6.6,19.5)
housing=housing.cut(box(-31.4,-5.6,14.6,62.8,6.8,9.8))
housing=housing.cut(cyl(3.7,7,0,-12,19.5,(0,1,0)))
def brow_section(x,depth,height,cy,cz,r):
 s=yzround(depth,height,.1,r,x,cy,cz)
 faces=[f for f in s.Faces if abs(f.CenterOfMass.x-x)<1e-5]
 return max(faces,key=lambda f:f.Area).OuterWire
# Fair the full-depth camera brow into the side rails instead of leaving box shoulders.
taper=Part.makeLoft([brow_section(31.5,9,12,-2.1,19.5,1.5),brow_section(45,5.5,7.8,.05,19,1.5),brow_section(60,3.5,5.8,1.55,18.7,1.4)],True,False)
housing=housing.fuse(taper).fuse(mirror(taper))
front=front.fuse(housing).cut(box(-31.4,-5.6,14.6,62.8,6.8,9.8))
front=front.cut(rr(63.4,10.4,5,2.4,0,1.2,19.5))
# Provisional USB connector/cable access at left board end; actual mate still required.
front=front.cut(box(-36,-4.8,16,7,6.6,7))
add('Slim_Front_And_Camera_Brow',front,note='Arducam B0441 sourced62x9x6mm camera/mic envelope in central brow. No XIAO or large side box. Port registration, mount, connector, mic vent, thermal and full FoV require sample. Lens retention/material open.')
door=rr(62.8,9.8,1,2.1,0,2,19.5)
add('Camera_Service_Back',door,note='Brow service lid envelope; selected retention/sealing/cable routing require detailed design.')
add('Camera_B0441_62x9x6_Envelope',cam,'ref','Arducam B0441 datasheet p3 table/drawing, manufacturer-authored PDF retrieved via distributor. Bounding envelope ONLY, not maker CAD or a purchased sample.6mm total depth per table. Lens centre currently a target, no live audio/video/sync demonstrated.')

for sign in [-1,1]:
 side='Left' if sign<0 else 'Right'
 # Root blends into a long slender temple instead of a rectangular electronics box.
 x=sign*73.5
 arm=Part.makeLoft([ellipse(x,10,16,2.2,4.8),ellipse(sign*75,28,16,2.15,4),ellipse(sign*76,65,14,1.8,3.8),ellipse(sign*75,99,13,1.65,3.3),ellipse(sign*72,126,9,1.6,3),ellipse(sign*69,143,-1,1.5,2.7)],True,False)
 # Rail provides fore/aft adjustment, not automatic comfort or calibrated contact force.
 rail=box(-75.2,51,10.7,1.5,38,6.6)
 for cy in [60,79]:
  slot=box(-76,cy-3,13.1,4,6,1.8).fuse(cyl(.9,4,-76,cy-3,14,(1,0,0))).fuse(cyl(.9,4,-76,cy+3,14,(1,0,0)))
  rail=rail.cut(slot)
 if sign>0:rail=mirror(rail)
 arm=arm.fuse(rail)
 add(side+'_Slim_Temple_With_Adjustment_Rail',arm,note='Rail and two slots provide a nominal +/-3mm carrier adjustment. No selected commercial hinge, fold kinematics, spring rate, contact force or stress qualification. Hinge interfaces are design targets only.')
 tip=Part.makeLoft([ellipse(sign*72,126,9,2.15,3.55),ellipse(sign*69,143,-1,2.05,3.25),ellipse(sign*68.3,147,-2.5,1.6,2.7)],True,False).cut(arm)
 add(side+'_Soft_Ear_Sleeve',tip,note='Candidate soft sleeve envelope; material and retention unqualified.')
 # Compact capsule around a DIFFERENT, source-listed13x7.4x5.6mm transducer.
 # Larger Adafruit1674 cannot fit this cavity and must not be silently reused.
 body=box(-71.2,63.5,10.3,5.6,13,7.4)
 cup=yzround(18.6,12.8,7.1,3.6,-72.4,70,14)
 cup=cup.cut(box(-71.45,63.25,10.05,7.2,13.5,7.9))
 # Sliding carrier joins the cup; spacers/compliant isolator are required at rail.
 carrier=box(-73.6,56.5,11,1.2,27,6)
 for cy in [60,79]:carrier=carrier.cut(cyl(.9,4,-75,cy,14,(1,0,0)))
 cup=cup.fuse(carrier)
 cap=yzround(18.6,12.8,.8,3.6,-65.3,70,14).fuse(box(-65.6,63.5,10.3,.3,13,7.4))
 # Two provisional retaining screws lie outside the transducer envelope.
 for zz in [8.9,19.1]:
  bore=cyl(.6,12,-75,70,zz,(1,0,0));cup=cup.cut(bore);cap=cap.cut(bore)
 cup=cup.cut(cyl(1.2,5,-68.2,76.5,12,(0,1,0)))
 if sign>0:body=mirror(body);cup=mirror(cup);cap=mirror(cap)
 add(side+'_Adjustable_BC_Capsule',cup,note='Source-sized compact receiver cup and sliding plate. Rail/clamp spacers, in/out adjustment, compliant isolation and preload are engineering gates, not validated mechanisms.')
 add(side+'_Insulating_Contact_Cap',cap,note='Provisional contact cap,0.8mm shell+0.3mm nominal coupling boss. Contact-face orientation is assumed; not qualified for skin or vibration transfer.')
 add(side+'_BS08_Envelope',body,'ref','Manufacturer catalog BS08:13x7.4x5.6mm,1.7+/-0.1g,8ohm nominal,0.8W listed. Catalog claim only; no purchased sample, full controlled drawing, transfer-function or clinical validation. RevD amplifier limits cannot be reused without requalification.')
 # Commercial hinge procurement target shown as a separate brushed metal insert.
 hinge=rr(5.5,4,4,1,sign*73.5,4,16)
 add(side+'_Hinge_Procurement_Envelope',hinge,'ref','Space reservation for selected eyewear hinge, not an internally engineered/tested folding hinge. No fold-flat claim.')

for x,name in [(-31.5,'Left'),(31.5,'Right')]:
 add(name+'_Lens_Reference',rr(50.4,35.2,1.2,8.8,x,1,0),'fit','Optical placeholder only; no prescription or qualified retention.')
 # Visible nose-pad stem and a separate rounded pad envelope.
 stem=cyl(.8,6,x/4,2,4,(0,1,0))
 add(name+'_Nose_Pad_Stem_Target',stem,'fit','Stock optical nose-pad mechanism target; attachment/adjustment must be selected.')
 m=A.Matrix();m.A11=3;m.A22=1.6;m.A33=5.4
 pad=Part.makeSphere(1).transformGeometry(m);pad.translate(V(x/4,8,2))
 add(name+'_Soft_Nose_Pad_Target',pad,'fit','Soft optical fit target, not qualified comfort.')

doc.addObject('App::DocumentObjectGroup','Mechanical_Form_Study').addObjects(parts)
doc.addObject('App::DocumentObjectGroup','Sourced_Envelopes_And_Procurement_Gates').addObjects(refs)
doc.addObject('App::DocumentObjectGroup','Optical_And_Fit_Targets').addObjects(fit)
doc.recompute()
invalid=[{'name':o.Name,'valid':o.Shape.isValid(),'solids':len(o.Shape.Solids)} for o in parts if not o.Shape.isValid() or len(o.Shape.Solids)!=1]
assert not invalid,invalid
hits=[]
for i,o in enumerate(parts):
 for p in parts[i+1:]:
  if not o.Shape.BoundBox.intersect(p.Shape.BoundBox):continue
  v=o.Shape.common(p.Shape).Volume
  if v>.05:hits.append([o.Name,p.Name,round(v,3)])
packaging=[]
for r in refs:
 if 'Envelope' not in r.Name or 'Hinge' in r.Name:continue
 for p in parts:
  if not r.Shape.BoundBox.intersect(p.Shape.BoundBox):continue
  v=r.Shape.common(p.Shape).Volume
  if v>.05:packaging.append([r.Name,p.Name,round(v,3)])
report={'revision':'E - wearability architecture and form STUDY, not manufacture release','native_validity':'PASS','part_count':len(parts),'static_intersections_mm3':hits,'component_overlap_mm3':packaging,'all_static_checks_pass':not hits and not packaging,'nominal_contact_cap_inner_span_mm':129,'listed_BS08_pair_mass_g':3.4,'pair_mass_status':'manufacturer catalog, not measured or including capsules','mechanical_solid_volume_cm3':round(sum(o.Shape.Volume for o in parts)/1000,3),'physical_comfort_verified':False,'folding_verified':False,'manufacturing_ready':False,'open_gates':['purchased miniature component verification','full mechanical drawings and contact face','camera mounting/USB connector/thermal field of view','hinge selection and folding','isolator, clamp spacers and contact preload','skin-contact material','lens retention and optical fitting','audio driver qualification and vibration feedback','human fit/weight/comfort','capture sync and realtime latency']}
print(json.dumps(report,indent=2),flush=True)
(out/'form_study_checks.json').write_text(json.dumps(report,indent=2))
doc.saveAs(str(out/'FOCUS_RevE_Wearability_Study.FCStd'))
Part.export(parts+refs+fit,str(out/'FOCUS_RevE_Wearability_Study.step'))
# Manufacturing STLs deliberately omitted: this is a fit/form study with open interfaces.
shutil.copy2(__file__,out/'build_reve.py')
