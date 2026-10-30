"""FOCUS Rev A: script-driven BRep prototype, dimensions in mm.
Run with FreeCAD's bundled python.exe. No optical prescription or electronics simulation.
"""
from pathlib import Path
import json, math, shutil
import FreeCAD as App
import Part, Mesh

ROOT=Path('A:/Focus_Ux/hardware_revA')
OUT=ROOT/'mechanical'; OUT.mkdir(parents=True,exist_ok=True)
doc=App.newDocument('FOCUS_RevA')
P={
 'frame_width_mm':146,'lens_opening_width_mm':50,'lens_opening_height_mm':34,
 'front_thickness_mm':5,'temple_pivot_x_mm':70,'temple_length_mm':139,
 'camera_module_mm':[38,38,19.01],'camera_xy_clearance_mm':0.8,
 'carrier_pcb_mm':[65,32,1.6],'control_pod_outer_mm':[79,44,28],
 'pcb_mount_holes_mm':[[3,3],[62,3],[3,29],[62,29]],
 'nominal_print_clearance_mm':0.4,'screw_clearance_M3_mm':3.4,
 'NOTE':'Prototype assumptions, not fit/comfort/strength certification. Camera holes and switches intentionally not inferred.'
}
parts=[]; refs=[]
def box(x,y,z,dx,dy,dz):return Part.makeBox(dx,dy,dz,App.Vector(x,y,z))
def cyl(r,h,x,y,z,axis=(0,0,1)):return Part.makeCylinder(r,h,App.Vector(x,y,z),App.Vector(*axis))
def rr(w,h,t,r,cx,y,cz):
 s=box(-w/2+r,-h/2,0,w-2*r,h,t).fuse(box(-w/2,-h/2+r,0,w,h-2*r,t))
 for a in [-1,1]:
  for b in [-1,1]:s=s.fuse(cyl(r,t,a*(w/2-r),b*(h/2-r),0))
 s=s.removeSplitter();s.rotate(App.Vector(),App.Vector(1,0,0),90);s.translate(App.Vector(cx,y+t,cz));return s
def add(name,shape,color,ref=False,note=''):
 o=doc.addObject('Part::Feature',name);o.Label=name.replace('_',' ');o.Shape=shape.removeSplitter()
 o.addProperty('App::PropertyString','EngineeringNote','FOCUS');o.EngineeringNote=note
 try:o.ViewObject.ShapeColor=color
 except Exception:pass
 (refs if ref else parts).append(o);return o

# Print part 1: frame with empty lens apertures; not optical/safety eyewear.
front=None
for x in [-34,34]:
 ring=rr(60,44,5,12,x,0,0).cut(rr(50,34,7,8,x,-1,0))
 front=ring if front is None else front.fuse(ring)
front=front.fuse(rr(12,8,5,3,0,0,12))
for sign in [-1,1]:
 x=sign*70
 tab=box(x-3,0,8,6,13,8).fuse(box(min(sign*61,x),0,8,9,5,8))
 front=front.fuse(tab).cut(cyl(1.7,12,x,8,6))
 # Strap holes are through the pivot tabs, separate from pivot.
front=front.removeSplitter()
add('Front_Frame',front,(0.12,0.19,0.23),note='Empty lens openings; no prescription lenses, impact rating or verified facial fit. M3 pivot holes.')

# Temples are separate printable parts. Stacked pivots, provisional M3 screw joints.
for sign,name in [(-1,'Left_Temple'),(1,'Right_Temple')]:
 x=sign*70
 arm=box(x-3,8,17,6,115,6).fuse(cyl(5,6,x,8,17))
 # Provisional ear hook drops 15 mm over 24 mm length; no ergonomic validation.
 pts=[App.Vector(x-3,116,17),App.Vector(x-3,136,2),App.Vector(x-3,147,2),App.Vector(x-3,147,8),App.Vector(x-3,139,8),App.Vector(x-3,120,23)]
 face=Part.Face(Part.makePolygon(pts+[pts[0]]));arm=arm.fuse(face.extrude(App.Vector(6,0,0)))
 arm=arm.cut(cyl(1.7,10,x,8,15))
 arm=arm.cut(cyl(1.6,10,x-5,141,5,(1,0,0)))
 if sign==1:
  for y in [45,85]:arm=arm.cut(cyl(1.2,12,64,y,20,(1,0,0)))
 add(name,arm,(0.14,0.23,0.27),note='Source-script adjustable temple; fit and pivot wear unverified. Add a support strap during bench trials.')

# Camera cradle: envelope-based, open optical/acoustic face, retention strap slots.
cradle=box(-22,-5,18,44,2,44)
cradle=cradle.fuse(box(-22,-26,18,44,23,2))
for x in [-22,19.8]:
 wall=box(x,-12,20,2.2,9,40)
 wall=wall.cut(box(x-1,-10,36,4.2,4,10))
 cradle=cradle.fuse(wall)
# Twin ears on front-frame top; M2 through fasteners across y.
for x in [-12,12]:
 cradle=cradle.fuse(box(x-3,-3,16,6,3,9)).cut(cyl(1.2,12,x,-7,20,(0,1,0)))
 front.Shape if False else None
 # Cut matching holes into frame at top rim (x +-12 intersects rounded lens rim).
 parts[0].Shape=parts[0].Shape.cut(cyl(1.2,10,x,-2,20,(0,1,0))).removeSplitter()
add('Camera_Cradle',cradle,(0.2,0.38,0.42),note='Fits published 38x38x19.01mm envelope; retention by two narrow straps through side slots. PCB edge, connector and microphone clearance require physical verification. No invented camera screw pattern.')
camera=box(-19,-25.01,20,38,19.01,38)
obj=add('REFERENCE_Camera_Envelope',camera,(0.68,0.53,0.26),True,'Waveshare GC2093 2MP USB Camera (A), published outer envelope only. Internal lens/connector geometry not inferred.')

# Carrier PCB sits sideways in a serviceable outer-temple pod.
# KiCad screen(u,v) has raw STEP (u,-v,z). Rz+90 rawSTEP then translate
# (83,30,-4) gives global(83+v,30+u,-4+z), a proper 3D rotation.
case=box(77,23,-9,44,79,28).cut(box(79,25,-7,40,75,29))
for u,v in P['pcb_mount_holes_mm']:
 x,y=83+v,30+u
 case=case.fuse(cyl(2.5,3,x,y,-7)).cut(cyl(0.8,7,x,y,-10))
lid_centers=[(81,27),(117,27),(81,98),(117,98)]
for x,y in lid_centers:
 case=case.fuse(cyl(2.5,26,x,y,-7)).cut(cyl(0.8,27,x,y,-6))
# Pico USB faces the front edge u=0. Ample provisional plug throat.
case=case.cut(box(90,21,1,18,7,15))
# Cable exits for dry-contact switches: no unselected switch bushing dimensions.
case=case.cut(box(102,98,5,12,6,7))
for y in [45,85]:
 case=case.fuse(box(73,y-5,17,6,10,6)).cut(cyl(1.2,10,71,y,20,(1,0,0)))
add('Control_Pod_Base',case,(0.14,0.23,0.27),note='USB-powered Pico control carrier only. No camera/AI power path. Four M2 PCB standoffs, pilot holes need sizing for chosen fastener/material. External switch harness exit.')
lid=box(77,23,19,44,79,2)
for x,y in lid_centers:lid=lid.cut(cyl(1.1,5,x,y,18))
lid=lid.cut(box(102,98,18,12,6,5))
for y in [45,85]:lid=lid.cut(box(76,y-5.2,18,3.2,10.4,5))
lid=lid.cut(box(88,30,18,10,6,5))
# Modest ventilation slots, placed away from edges and screws.
for y in [43,49,55,61,67,73]:lid=lid.cut(box(89,y,18,19,2,5))
add('Control_Pod_Lid',lid,(0.2,0.38,0.42),note='Prototype lid; four M2 screws, ventilation; not a thermal qualification. Cable controls remain external until switch selection is fixed.')

carrier=box(83,30,-4,32,65,1.6)
for u,v in P['pcb_mount_holes_mm']:carrier=carrier.cut(cyl(1.2,3,83+v,30+u,-4.5))
add('REFERENCE_Carrier_PCB',carrier,(0.16,0.47,0.3),True,'Matches KiCad board envelope/mount holes; replace by exported populated STEP for exact collision review.')
# Pico envelope and headers are conservative placeholders, never manufacturer CAD.
add('REFERENCE_Pico_Envelope',box(88.5,37,6.1,21,51,5.5),(0.18,0.52,0.32),True,'51x21mm PCB sourced from Pico datasheet; assembly height is a conservative assumption pending actual headers/USB plug.')
for x in [89.61,107.39]:add('REFERENCE_Socket_'+str(int(x)),box(x-1.27,37.1,-2.4,2.54,48.8,8.5),(0.25,0.25,0.28),True,'Generic 1x20 socket envelope, exact selected connector height must be verified.')
add('REFERENCE_USB_Plug_Clearance',box(91,17,2,16,22,12),(0.52,0.55,0.57),True,'Provisional cable-plug keepout; choose actual micro-USB cable before accepting fit.')

# Use the actual KiCad STEP in the native assembly when exported and valid.
actual_step=ROOT/'electronics/focus_control_board.step'
if actual_step.exists():
 imported=Part.read(str(actual_step))
 if imported.isNull() or not imported.isValid():raise RuntimeError('Invalid electronics STEP')
 # Verified raw KiCad STEP: x0..65, y-32..0; preserve raw axes to avoid a mirror.
 bb=imported.BoundBox
 if abs(bb.XLength-65)>0.1 or abs(bb.YLength-32)>0.1:raise RuntimeError('Unexpected PCB STEP envelope '+str((bb.XLength,bb.YLength)))
 if abs(bb.XMin)>0.1 or abs(bb.YMax)>0.1:raise RuntimeError('Unexpected KiCad raw STEP origin')
 imported.rotate(App.Vector(),App.Vector(0,0,1),90);imported.translate(App.Vector(83,30,-4-bb.ZMin))
 native=add('ACTUAL_KiCad_Carrier_PCB',imported,(0.16,0.47,0.3),True,'Actual board-only STEP from KiCad; populated connector and Pico envelopes still provisional.')
 refs=[o for o in refs if o.Name!='REFERENCE_Carrier_PCB']
 doc.removeObject('REFERENCE_Carrier_PCB')

doc.addObject('App::DocumentObjectGroup','Printable_Parts').addObjects(parts)
doc.addObject('App::DocumentObjectGroup','Reference_Envelopes').addObjects(refs)
doc.recompute()
for o in parts+refs:
 if not o.Shape.isValid():raise RuntimeError('Invalid BRep: '+o.Name)
 if len(o.Shape.Solids)!=1:raise RuntimeError('Not single solid: '+o.Name+':'+str(len(o.Shape.Solids)))
doc.recompute();doc.saveAs(str(OUT/'FOCUS_Glasses_RevA.FCStd'))
Part.export(parts+refs,str(OUT/'FOCUS_Glasses_RevA_Assembly.step'))
stl=OUT/'stl';stl.mkdir(exist_ok=True)
meshdata=[]
for o in parts:
 # Translation to bed and negative-Y front rotation retained in native assembly.
 shape=o.Shape.copy();b=shape.BoundBox;shape.translate(App.Vector(-b.XMin,-b.YMin,-b.ZMin))
 temp=doc.addObject('Part::Feature','Export_'+o.Name);temp.Shape=shape
 Mesh.export([temp],str(stl/(o.Name+'.stl')));doc.removeObject(temp.Name)
 # Low-resolution triangulation for illustrative multi-view preview.
 vv,ff=o.Shape.tessellate(0.8)
 meshdata.append({'name':o.Name,'ref':False,'vertices':[[v.x,v.y,v.z] for v in vv],'faces':ff})
for o in refs:
 vv,ff=o.Shape.tessellate(1.0)
 meshdata.append({'name':o.Name,'ref':True,'vertices':[[v.x,v.y,v.z] for v in vv],'faces':ff})

checks=[]
for i,a in enumerate(parts):
 for b in parts[i+1:]:
  vol=a.Shape.common(b.Shape).Volume
  if vol>0.01:checks.append({'part_a':a.Name,'part_b':b.Name,'overlap_mm3':round(vol,4)})
report={'status':'engineering prototype - not manufacturing release','parameters':P,
 'parts':[{'name':o.Name,'valid':o.Shape.isValid(),'solids':len(o.Shape.Solids),'volume_mm3':round(o.Shape.Volume,2),'bbox_mm':[round(o.Shape.BoundBox.XLength,2),round(o.Shape.BoundBox.YLength,2),round(o.Shape.BoundBox.ZLength,2)]} for o in parts],
 'print_part_intersections':checks,
 'reference_geometry_excluded_from_collision_certification':True,
 'unverified':['human fit and load balance','camera edge retention and mic/cable clearance','actual socket and plug dimensions','pilot hole sizing after material/fastener choice','hinge fastener stack and strap design','thermal, drop, sweat, optical and acoustic performance']}
(OUT/'geometry_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
(OUT/'preview_mesh.json').write_text(json.dumps(meshdata),encoding='utf-8')
(OUT/'parameters.json').write_text(json.dumps(P,indent=2),encoding='utf-8')
shutil.copy2(Path(__file__),OUT/'build_mechanical.py')
print(json.dumps({'native':str(OUT/'FOCUS_Glasses_RevA.FCStd'),'print_parts':len(parts),'intersections':checks},indent=2))
