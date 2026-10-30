"""Bounded exact-BRep motion/clearance checks. Not physical or FEA validation."""
from pathlib import Path
import json,time
import FreeCAD as A,Part
root=Path('A:/Focus_Ux/hardware_revD');out=root/'tests';out.mkdir(exist_ok=True)
d=A.openDocument(str(root/'mechanical/FOCUS_RevD_Industrial_Review.FCStd'))
V=A.Vector
mechanical=d.getObject('Mechanical_Review_Parts').Group
module=d.getObject('Manufacturer_Sense_Assembly').Shape
threshold=.05
checks=[]
def record(n,status,data):checks.append({'test':n,'status':status,'data':data});print(n,status,flush=True)

record('BRep validity and solids','PASS' if all(o.Shape.isValid() and len(o.Shape.Solids)==1 for o in mechanical) else 'FAIL',{'part_count':len(mechanical)})
static=[]
for i,a in enumerate(mechanical):
 for b in mechanical[i+1:]:
  vol=a.Shape.common(b.Shape).Volume
  if vol>threshold:static.append({'a':a.Name,'b':b.Name,'mm3':round(vol,3)})
record('Open-position part interference','FAIL' if static else 'PASS',static)

clear=[]
for n in ['Front_Capture_Chassis','Right_Service_Door','Right_Temples']:
 s=d.getObject(n).Shape
 vol=s.common(module).Volume
 clear.append({'part':n,'min_clearance_mm':None,'overlap_mm3':round(vol,4),'note':'Exact minimum-distance solve not completed; this checks overlap only.'})
record('Actual manufacturer module overlap','PASS' if all(x['overlap_mm3']<=threshold for x in clear) else 'FAIL',clear)

gauge=[]
for x in [-68,73]:
 cylinder=Part.makeCylinder(1.25,25,V(x,24,4),V(0,0,1))
 for n in ['Front_Capture_Chassis','Left_Temples' if x<0 else 'Right_Temples']:
  vol=d.getObject(n).Shape.common(cylinder).Volume
  gauge.append({'pivot_x_mm':x,'part':n,'gauge_diameter_mm':2.5,'overlap_mm3':round(vol,4)})
record('Nominal hinge pin gauge','PASS' if all(x['overlap_mm3']<=threshold for x in gauge) else 'FAIL',gauge)

# Test only camera-centre forward probe, not full FoV or optical axis calibration.
probe=Part.makeCylinder(.4,45,V(72.5,-55,17),V(0,1,0))
opt=[]
for n in ['Front_Capture_Chassis','Right_Service_Door']:
 vol=d.getObject(n).Shape.common(probe).Volume
 opt.append({'part':n,'probe_overlap_mm3':round(vol,4)})
record('Nominal camera centreline access','PASS' if all(x['probe_overlap_mm3']<=threshold for x in opt) else 'FAIL',{'note':'Bounding-geometry centreline only; full FoV not evaluated','parts':opt})

fixed=[('chassis',d.getObject('Front_Capture_Chassis').Shape),('door',d.getObject('Right_Service_Door').Shape),('module',module)]
sweeps=[]
for side,x,sgn in [('Left',-68,-1),('Right',73,1)]:
 arm=d.getObject(side+'_Temples').Shape
 sleeve=Part.makeCompound([d.getObject(side+n).Shape for n in ['_Ear_Sleeve','_BC_Cradle','_BC_Contact_Cover','_BC_Transducer_Envelope']])
 samples=[]
 for angle in list(range(0,91,5)):
  moving=arm.copy();moving.rotate(V(x,24,0),V(0,0,1),sgn*angle)
  sh=sleeve.copy();sh.rotate(V(x,24,0),V(0,0,1),sgn*angle)
  hits=[]
  for name,obstacle in fixed:
   # Bounding rejection prevents expensive Boolean on well-separated objects.
   bb=Part.makeCompound([moving,sh]).BoundBox;bo=obstacle.BoundBox
   if not bb.intersect(bo):continue
   vol=moving.common(obstacle).Volume+sh.common(obstacle).Volume
   if vol>threshold:hits.append({'obstacle':name,'overlap_mm3':round(vol,3)})
  samples.append({'fold_deg':angle,'interferences':hits})
  print('motion',side,angle,'FAIL' if hits else 'clear',flush=True)
 sweeps.append({'side':side,'direction_about_z':sgn,'samples':samples})
record('Independent temple fold sweep','FAIL' if any(x['interferences'] for side in sweeps for x in side['samples']) else 'PASS',sweeps)

# The two assemblies must also be able to fold together, not only independently.
left=Part.makeCompound([d.getObject('Left'+n).Shape for n in ['_Temples','_Ear_Sleeve','_BC_Cradle','_BC_Contact_Cover','_BC_Transducer_Envelope']])
right=Part.makeCompound([d.getObject('Right'+n).Shape for n in ['_Temples','_Ear_Sleeve','_BC_Cradle','_BC_Contact_Cover','_BC_Transducer_Envelope']])
paired=[]
left.rotate(V(-68,24,0),V(0,0,1),-90)
for angle in list(range(0,91,5)):
 r=right.copy();r.rotate(V(73,24,0),V(0,0,1),angle)
 vol=left.common(r).Volume
 if vol>threshold:paired.append({'left_deg':90,'right_deg':angle,'overlap_mm3':round(vol,3)})
 print('paired fold',angle,'FAIL' if vol>threshold else 'clear',flush=True)
record('Sequential fold left then right','FAIL' if paired else 'PASS',paired)
bc=[]
for side in ['Left','Right']:
 b=d.getObject(side+'_BC_Transducer_Envelope').Shape
 for p in mechanical:
  overlap=b.common(p.Shape).Volume
  if overlap>threshold:bc.append({'transducer':side,'part':p.Name,'overlap_mm3':round(overlap,3)})
record('Transducer envelope packaging overlap','FAIL' if bc else 'PASS',bc)

retention=[]
for side,sign in [('Left',1),('Right',-1)]:
 b=d.getObject(side+'_BC_Transducer_Envelope').Shape.copy()
 b.translate(V(sign*1.1,0,0))
 overlap=b.common(d.getObject(side+'_BC_Contact_Cover').Shape).Volume
 retention.append({'side':side,'outward_translation_mm':1.1,'blocking_overlap_mm3':round(overlap,3)})
record('Nominal outward escape blocked by cover','PASS' if all(x['blocking_overlap_mm3']>threshold for x in retention) else 'FAIL',{'note':'Geometric blocking only; fastener/material/force not validated','sides':retention})

volume=sum(o.Shape.Volume for o in mechanical)/1000
record('Material volume screening','INFO',{'solid_part_volume_cm3':round(volume,3),'mass_formula':'mass_g = actual_material_density_g_cm3 * solid_volume_cm3; infill, supports, electronics and fasteners not included','measured_weight':False})
report={'scope':'Exact-BRep static and sampled kinematic screening only, RevD with complete cradle and transducer envelopes',
 'interference_threshold_mm3':threshold,'tests':checks,'physical_validation':False,
 'not_tested':['full FoV and optical performance','dynamic continuous collision between sampled angles','mechanical stress, fatigue, fastener preload and drop','RF/antenna, temperature and battery current','real video/audio transport, extraction quality and capture-to-ear delay','comfort, retention and human fit'],
 'overall':'FAIL' if any(c['status']=='FAIL' for c in checks) else 'PASS_WITH_PHYSICAL_GATES_OPEN'}
(out/'virtual_test_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('overall',report['overall'],flush=True)
