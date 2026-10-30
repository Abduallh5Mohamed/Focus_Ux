import os
os.environ['QT_QPA_PLATFORM']='windows'
import FreeCAD as App, FreeCADGui as Gui
from pathlib import Path
Gui.showMainWindow()
import PartGui
Gui.getMainWindow().hide()
root=Path('A:/Focus_Ux/hardware_revA')
doc=App.openDocument(str(root/'mechanical/FOCUS_Glasses_RevA.FCStd'))
for o in doc.Objects:
 if not hasattr(o,'Shape') or not hasattr(o.ViewObject,'ShapeColor'):continue
 o.ViewObject.Visibility=True
 o.ViewObject.LineColor=(0.05,0.08,0.10)
 if o.Name.startswith('REFERENCE'):
  o.ViewObject.ShapeColor=(0.78,0.60,0.26);o.ViewObject.Transparency=45
 elif o.Name.startswith('ACTUAL'):
  o.ViewObject.ShapeColor=(0.14,0.49,0.30)
 else:o.ViewObject.ShapeColor=(0.10,0.24,0.28)
view=Gui.activeDocument().activeView()
view.setAnimationEnabled(False)
Gui.updateGui()
view.viewAxonometric();Gui.updateGui();view.fitAll();Gui.updateGui()
print('iso',view.getCameraOrientation())
view.saveImage(str(root/'previews/assembly_isometric.png'),1600,1100,'White')
view.viewFront();Gui.updateGui();view.fitAll();Gui.updateGui()
view.saveImage(str(root/'previews/assembly_front.png'),1600,1000,'White')
view.viewTop();Gui.updateGui();view.fitAll();Gui.updateGui()
view.saveImage(str(root/'previews/assembly_top.png'),1600,1000,'White')
Gui.activeDocument().activeView().viewAxonometric();Gui.activeDocument().activeView().fitAll()
doc.recompute();doc.save()
print('Native FreeCAD views saved.')
