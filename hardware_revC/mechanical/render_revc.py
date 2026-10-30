import os
os.environ['QT_QPA_PLATFORM']='windows'
import FreeCAD as A,FreeCADGui as G
from pathlib import Path
G.showMainWindow();import PartGui
G.getMainWindow().hide()
root=Path('A:/Focus_Ux/hardware_revC')
d=A.openDocument(str(root/'mechanical/FOCUS_RevC_Industrial_Review.FCStd'))
for o in d.Objects:
 if o.TypeId!='Part::Feature' or not hasattr(o.ViewObject,'ShapeColor'):continue
 o.ViewObject.Visibility=True;o.ViewObject.DisplayMode='Shaded'
 o.ViewObject.Deviation=.05;o.ViewObject.AngularDeflection=8
 o.ViewObject.LineColor=(.06,.08,.10)
 if 'Lens_Reference' in o.Name:
  o.ViewObject.ShapeColor=(.52,.66,.72);o.ViewObject.Transparency=78
 elif 'Nose_Pad' in o.Name or 'Ear_Sleeve' in o.Name:
  o.ViewObject.ShapeColor=(.15,.32,.34)
 elif o.Name=='Manufacturer_Sense_Assembly':
  # CAD of real PCB/components is separately inspectable. Color front lens faces dark.
  o.ViewObject.ShapeColor=(.12,.22,.18)
  o.ViewObject.DiffuseColor=[(.025,.04,.055) if f.CenterOfMass.y < -10 else (.16,.24,.19) for f in o.Shape.Faces]
 elif o.Name=='Right_Service_Door':o.ViewObject.ShapeColor=(.18,.24,.26)
 else:o.ViewObject.ShapeColor=(.11,.15,.18)
sk=d.getObject('Lens_Opening_Datums');sk.ViewObject.Visibility=False
v=G.activeDocument().activeView();v.setAnimationEnabled(False);G.updateGui()
v.viewAxonometric();G.updateGui();v.fitAll();G.updateGui()
v.saveImage(str(root/'previews/RevC_isometric.png'),1800,1200,'White')
v.viewFront();G.updateGui();v.fitAll();G.updateGui()
v.saveImage(str(root/'previews/RevC_front.png'),1800,850,'White')
v.viewTop();G.updateGui();v.fitAll();G.updateGui()
v.saveImage(str(root/'previews/RevC_top.png'),1600,1100,'White')
# Review view: hidden module surrounded by chassis/service opening.
for n in ['Right_Service_Door','Right_Temples','Right_Ear_Sleeve']:d.getObject(n).ViewObject.Visibility=False
d.getObject('Front_Capture_Chassis').ViewObject.Transparency=75
v.viewAxonometric();G.updateGui();v.fitAll();G.updateGui()
v.saveImage(str(root/'previews/RevC_hardware_fit.png'),1800,1200,'White')
for n in ['Right_Service_Door','Right_Temples','Right_Ear_Sleeve']:d.getObject(n).ViewObject.Visibility=True
d.getObject('Front_Capture_Chassis').ViewObject.Transparency=0
v.viewAxonometric();G.updateGui();v.fitAll();G.updateGui();d.save()
print('RevC native renders completed.')
