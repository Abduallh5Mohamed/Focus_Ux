import os
os.environ['QT_QPA_PLATFORM']='windows'
import FreeCAD as A,FreeCADGui as G
from pathlib import Path
G.showMainWindow();import PartGui
G.getMainWindow().hide()
root=Path('A:/Focus_Ux/hardware_revB')
d=A.openDocument(str(root/'mechanical/FOCUS_RevB_Clip_Packaging.FCStd'))
for o in d.Objects:
 if not hasattr(o,'Shape') or not hasattr(o.ViewObject,'ShapeColor'):continue
 o.ViewObject.Visibility=True
 o.ViewObject.LineColor=(.05,.08,.10)
 if o.Name.startswith('CONTEXT'):o.ViewObject.ShapeColor=(.15,.18,.20)
 elif o.Name.startswith('REFERENCE'):o.ViewObject.ShapeColor=(.74,.55,.23);o.ViewObject.Transparency=45
 else:o.ViewObject.ShapeColor=(.08,.36,.36)
v=G.activeDocument().activeView();v.setAnimationEnabled(False)
v.viewAxonometric();G.updateGui();v.fitAll();G.updateGui()
v.saveImage(str(root/'previews/RevB_isometric.png'),1600,1050,'White')
v.viewFront();G.updateGui();v.fitAll();G.updateGui()
v.saveImage(str(root/'previews/RevB_front.png'),1600,850,'White')
v.viewAxonometric();G.updateGui();v.fitAll();G.updateGui();d.save()
print('RevB native views saved.')
