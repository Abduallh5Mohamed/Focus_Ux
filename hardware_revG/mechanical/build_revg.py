"""RevG independent packaging study. All units mm. No production geometry claim."""
import FreeCAD as A, Part, math, json, csv
from pathlib import Path
V=A.Vector
R=Path('A:/Focus_Ux/hardware_revG'); O=R/'mechanical'
doc=A.newDocument('FOCUS_RevG_Standalone_Packaging_Study'); items=[]
def box(x,y,z,w,l,h): return Part.makeBox(w,l,h,V(x,y,z))
def rounded(x,y,z,w,l,h,r=2):
 s=box(x+r,y,z,w-2*r,l,h).fuse(box(x,y+r,z,w,l-2*r,h))
 for xx in [x+r,x+w-r]:
  for yy in [y+r,y+l-r]:s=s.fuse(Part.makeCylinder(r,h,V(xx,yy,z)))
 return s.removeSplitter()
def add(name,s,kind='mechanical',side='fixed',evidence='',mass=None,density=None):
 o=doc.addObject('Part::Feature',name);o.Shape=s.removeSplitter()
 for prop,value in [('EvidenceBoundary',evidence),('Category',kind),('MotionGroup',side)]:
  o.addProperty('App::PropertyString',prop,'FOCUS');setattr(o,prop,value)
 m=mass if mass is not None else (s.Volume/1000*density if density else None)
 items.append((o,kind,side,m,'supplier catalog' if mass is not None else ('assumed density '+str(density)+' g/cm3' if density else 'UNKNOWN; excluded from subtotal')))
 return o
# Wider modular temples are driven by real modem and cell envelopes, not a slimness claim.
front=rounded(-79,-9,20,158,11,14).cut(box(-31.4,-7,21.6,62.8,7.4,9.8))
front=front.cut(Part.makeCylinder(3.5,5,V(0,-11,26),V(0,1,0)))
for x in [-58,7]:
 rim=rounded(x,-1,-17,51,3,38,1.4).cut(box(x+2,-2,-15,47,5,34))
 front=front.fuse(rim)
add('Front_Brow_And_Rims',front,evidence='1.5-2 mm nominal walls; optical/lens datum and skin fit unqualified',density=1.15)
add('Camera_B0441_Source_Envelope',box(-31,-6.6,22,62,6,9),'source','fixed','B0441 historical manufacturer table 62x9x6; lens/connector registration provisional')
for side,sgn in [('Left',-1),('Right',1)]:
 x=-99 if sgn<0 else 68;w=31 if sgn<0 else 38
 outer=rounded(x,8,8,w,139,23,4)
 cavity=rounded(x+1.5,9.5,9.5,w-3,136,23,3)
 shell=outer.cut(cavity)
 # Removable rigid temples: no fabricated hinge performance implied.
 add(side+'_Removable_Temple_Tray',shell,side=side,evidence='Rigid detachable bench assembly; fasteners and retention TBD. NOT a functional folding hinge.',density=1.15)
 add(side+'_Service_Lid',rounded(x,8,31.3,w,139,1.2,4),side=side,evidence='0.3mm service seam; retention/seal not engineered',density=1.15)
 # Conservative continuous wire corridor includes insulation and routing clearance.
 wx=-70.7 if sgn<0 else 70.7
 add(side+'_Wire_Clearance_Envelope',Part.makeCylinder(.65,131,V(wx,12,27),V(0,1,0)),'wire',side,'1.3mm corridor only, actual harness/USB impedance/bend radius unresolved')
 # Bare transducer and carrier lie inward of the electronic temples.
 tx=-66 if sgn<0 else 60.4
 add(side+'_BS08_Source_Envelope',box(tx,91,14,5.6,13,7.4),'source',side,'BS08 catalog13x7.4x5.6, orientation assumed',mass=1.7)
 carrier=box(-68 if sgn<0 else 59,89,12,9,17,11).cut(box(tx-.3,90.7,13.7,6.2,13.6,8))
 add(side+'_BC_Insulating_Carrier',carrier,side=side,evidence='Contact pressure/spring/skin material unqualified; requires compliant adjustment',density=1.15)
 # Interconnect at root is a swept full motion keepout, not a routed flex.
 add(side+'_Root_Wire_Bend_Reservation',Part.makeCylinder(2,5,V(sgn*74,3,26),V(0,1,0)),'wire',side,'4mm diameter bridge reservation; no fatigue or bend-radius qualification')
add('Battery_Protected_Pack_Allowance',box(-95,70,11,22,65,12),'reservation','Left','65x22x12 provisional protected-pack solution, NOT a chosen cell or duration solution')
add('Tattu_500mAh_Reference_Only',box(-93,73,12,18,58,8),'nested','Left','Historical Tattu58x18x8/14g reference. Not selected, not claimed runtime.',mass=14)
add('Power_Audio_PCB_Solution_Allowance',box(-95,15,11,24,42,10),'reservation','Left','24x42x10 assumed complete PCB solution; no routed board fit proof')
add('Modem_PCB_Solution_Allowance',box(73,15,11,30,42,8),'reservation','Right','30x42x8 PROVISIONAL board solution; USB/SIM/RF clearance may enlarge it')
add('A7670E_Bare_Module_Source',box(76,20,13,24,24,2.3),'nested','Right','SIMCom bare24x24x2.3 only; not whole modem PCB')
add('NanoSIM_Access_Allowance',box(83,45,20,16,15,3),'reservation','Right','16x15x3 provisional socket/board reservation; selected socket drawing needed')
add('NanoSIM_Insertion_Travel',box(83,45,23.4,16,15,7),'service','Right','Top service access with lid removed; path not an IP-rated user door')
add('Host_PCB_Solution_Allowance',box(74,70,11,24,48,10),'reservation','Right','24x48x10 assumed P4/USB-hub/memory full solution; routing/thermal feasibility unproven')
add('RF_Antenna_Keepout',box(74,122,11,15,23,16),'keepout','Right','345mm2 rear region inadequate for historical42.6x12.1 flex without folding; ANTENNA SELECTION/PLACEMENT FAIL remains')
add('Host_Thermal_Clearance',box(75,71,22,22,46,4),'thermal','Right','Air/heat-spreader reserve; no thermal solution or verified cooling capacity')
for name,x,y,z in [('FL',-60,-7,27),('FR',60,-7,27),('TL',-94,62,27),('TR',99,62,27)]:
 side='fixed' if name[0]=='F' else ('Left' if name=='TL' else 'Right')
 # Front ports are separate housing pockets, which are cut below.
 m=add('Mic_'+name+'_PCB_Allowance',box(x-2,y-2,z-1,4,4,2),'reservation',side,'4x4x2 generic matched-digital-mic PCB reservation, not supplier body; shared clock and port mesh TBD')
 if side=='fixed':doc.getObject('Front_Brow_And_Rims').Shape=doc.getObject('Front_Brow_And_Rims').Shape.cut(box(x-2.3,y-2.3,z-1.3,4.6,4.6,2.6))
add('Battery_Larger_Scenario_Not_Fitted',box(-150,65,8,28,75,14),'alternative','alternative','75x28x14 hypothetical larger pack envelope; capacity/mass/vendor UNKNOWN. Separate alternative, not in assembly.')
doc.recompute()
# Exclude nested body within its encompassing PCB/pack allowance; containment is intentional.
active=[a for a in items if a[1] not in ['nested','alternative','thermal','service']]
def hits(objects):
 result=[]
 for i,(n,s) in enumerate(objects):
  for m,t in objects[i+1:]:
   if s.BoundBox.intersect(t.BoundBox):
    v=s.common(t).Volume
    if v>.05:result.append({'a':n,'b':m,'overlap_mm3':round(v,3)})
 return result
static=hits([(o.Name,o.Shape) for o,*_ in active])
# Candidate conventional inward folding around vertical roots. All modeled wires/components move.
# Samples do NOT prove continuous collision freedom; failed samples conclusively reject this layout.
sweep=[]
for mode in ['left_only','right_only','both']:
 for deg in range(0,91,5):
  shapes=[]
  for o,k,side,*_ in active:
   s=o.Shape.copy()
   if (side=='Left' and mode!='right_only') or (side=='Right' and mode!='left_only'):
    sign=1 if side=='Left' else -1
    s.rotate(V(-74 if side=='Left' else 74,6,26),V(0,0,1),-sign*deg)
   shapes.append((o.Name,s))
  h=hits(shapes)
  # Static collisions reported separately, remove baseline identical pair overlaps.
  baseline={frozenset([v['a'],v['b']]) for v in static}
  novel=[v for v in h if frozenset([v['a'],v['b']]) not in baseline]
  sweep.append({'mode':mode,'angle_deg':deg,'new_collisions':novel})
rows=[];mt=0;moment=V()
for o,k,side,m,basis in items:
 solids=o.Shape.Solids
 vol=sum(s.Volume for s in solids)
 c=sum((s.CenterOfMass*s.Volume for s in solids),V())/vol if vol else o.Shape.BoundBox.Center
 rows.append({'part':o.Name,'category':k,'mass_g':m if m is not None else 'UNKNOWN','mass_basis':basis,'cx_mm':c.x,'cy_mm':c.y,'cz_mm':c.z})
 if m is not None and k!='alternative':mt+=m;moment+=c*m
with (O/'mass_and_cg_estimate.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
rep={'revision':'G engineering packaging study','native_validity':[{'part':o.Name,'valid':o.Shape.isValid(),'solids':len(o.Shape.Solids)} for o,*_ in items],'static_collisions':static,'fold_sweep':sweep,'sweep_step_deg':5,'continuous_motion_proven':False,'selected_architecture':'rigid removable temples; folding unsupported','mass_subtotal_g':mt,'subtotal_cg_mm':list(moment/mt),'mass_scope':'polymer assumed1.15g/cm3 + catalog BS08 pair and reference500mAh only. ALL PCBs/camera/fasteners/wires/lenses/pads/antenna UNKNOWN; not complete product mass or CG','antenna_fit':'FAIL: rear keepout cannot contain historical42.6x12.1 flex flat','battery_runtime_verified':False,'physical_comfort_verified':False,'manufacturing_ready':False}
(O/'cad_checks.json').write_text(json.dumps(rep,indent=2))
doc.saveAs(str(O/'FOCUS_RevG_Standalone_Packaging_Study.FCStd'))
Part.export([o for o,k,*_ in items if k!='alternative'],str(O/'FOCUS_RevG_Standalone_Packaging_Study.step'))
print(json.dumps({'static':static,'sweep_failed_samples':sum(bool(v['new_collisions']) for v in sweep),'subtotal_mass_g':mt},indent=2))
