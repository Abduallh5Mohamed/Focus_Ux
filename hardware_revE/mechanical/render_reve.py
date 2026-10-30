import os
os.environ['QT_QPA_PLATFORM']='windows'
import FreeCAD as A,FreeCADGui as G
from pathlib import Path
G.showMainWindow();import PartGui
G.getMainWindow().hide()
root=Path('A:/Focus_Ux/hardware_revE')
d=A.openDocument(str(root/'mechanical/FOCUS_RevE_Wearability_Study.FCStd'))
for o in d.Objects:
 if o.TypeId!='Part::Feature':continue
 o.ViewObject.Visibility=True;o.ViewObject.DisplayMode='Shaded';o.ViewObject.Deviation=.04;o.ViewObject.AngularDeflection=8
 if 'Lens' in o.Name:o.ViewObject.ShapeColor=(.64,.75,.77);o.ViewObject.Transparency=83
 elif 'Hinge' in o.Name or 'Stem' in o.Name:o.ViewObject.ShapeColor=(.48,.52,.54)
 elif 'BS08' in o.Name:o.ViewObject.ShapeColor=(.5,.38,.21)
 elif 'Camera_B0441' in o.Name:o.ViewObject.ShapeColor=(.025,.035,.045)
 elif 'Contact_Cap' in o.Name or 'Nose_Pad' in o.Name:o.ViewObject.ShapeColor=(.14,.19,.20)
 elif 'Sleeve' in o.Name:o.ViewObject.ShapeColor=(.09,.15,.16)
 else:o.ViewObject.ShapeColor=(.085,.12,.14)
v=G.activeDocument().activeView();v.setAnimationEnabled(False);G.updateGui()
for name,view in [('isometric',v.viewAxonometric),('front',v.viewFront),('top',v.viewTop)]:
 view();G.updateGui();v.fitAll();G.updateGui();v.saveImage(str(root/'previews'/('RevE_'+name+'.png')),2200,1400,'White')
# Separate unambiguous packaging view: transparent capsules expose the sourced envelopes.
for side in ['Left','Right']:
 d.getObject(side+'_Adjustable_BC_Capsule').ViewObject.Transparency=75
 d.getObject(side+'_Insulating_Contact_Cap').ViewObject.Transparency=85
v.viewAxonometric();G.updateGui();v.fitAll();G.updateGui();v.saveImage(str(root/'previews/RevE_component_packaging.png'),2200,1400,'White')
for side in ['Left','Right']:
 d.getObject(side+'_Adjustable_BC_Capsule').ViewObject.Transparency=0
 d.getObject(side+'_Insulating_Contact_Cap').ViewObject.Transparency=0
v.viewAxonometric();G.updateGui();v.fitAll();G.updateGui();d.save()
print('RevE actual native CAD previews complete')

