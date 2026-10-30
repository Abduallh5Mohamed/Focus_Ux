"""Bounded exact-BRep motion/clearance checks. Not physical or FEA validation."""
from pathlib import Path
import json,time
import FreeCAD as A,Part
root=Path('A:/Focus_Ux/hardware_revC');out=root/'tests';out.mkdir(exist_ok=True)
d=A.openDocument(str(root/'mechanical/FOCUS_RevC_Industrial_Review.FCStd'))
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
 cylinder=Part.makeCylinder(1.25,25,V(x,9,4),V(0,0,1))
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
 sleeve=d.getObject(side+'_Ear_Sleeve').Shape
 samples=[]
 for angle in [0,5,10,15,30,45,60,75,90]:
  moving=arm.copy();moving.rotate(V(x,9,0),V(0,0,1),sgn*angle)
  sh=sleeve.copy();sh.rotate(V(x,9,0),V(0,0,1),sgn*angle)
  hits=[]
  for name,obstacle in fixed:
   # Bounding rejection prevents expensive Boolean on well-separated objects.
   bb=moving.BoundBox;bo=obstacle.BoundBox
   if not bb.intersect(bo):continue
   vol=moving.common(obstacle).Volume+sh.common(obstacle).Volume
   if vol>threshold:hits.append({'obstacle':name,'overlap_mm3':round(vol,3)})
  samples.append({'fold_deg':angle,'interferences':hits})
  print('motion',side,angle,'FAIL' if hits else 'clear',flush=True)
 sweeps.append({'side':side,'direction_about_z':sgn,'samples':samples})
record('Independent temple fold sweep','FAIL' if any(x['interferences'] for side in sweeps for x in side['samples']) else 'PASS',sweeps)

volume=sum(o.Shape.Volume for o in mechanical)/1000
record('Material volume screening','INFO',{'solid_part_volume_cm3':round(volume,3),'mass_formula':'mass_g = actual_material_density_g_cm3 * solid_volume_cm3; infill, supports, electronics and fasteners not included','measured_weight':False})
report={'scope':'Exact-BRep static and sampled kinematic screening only, RevC unmodified',
 'interference_threshold_mm3':threshold,'tests':checks,'physical_validation':False,
 'not_tested':['full FoV and optical performance','dynamic continuous collision between sampled angles','temple-to-temple interaction when sequentially folded','mechanical stress, fatigue, fastener preload and drop','RF/antenna, temperature and battery current','real video/audio transport, extraction quality and capture-to-ear delay','comfort, retention and human fit'],
 'overall':'FAIL' if any(c['status']=='FAIL' for c in checks) else 'PASS_WITH_PHYSICAL_GATES_OPEN'}
(out/'virtual_test_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('overall',report['overall'],flush=True)
