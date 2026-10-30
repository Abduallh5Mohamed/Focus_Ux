import os
os.environ['QT_QPA_PLATFORM']='windows'
import FreeCAD as A,FreeCADGui as G,PartGui
from pathlib import Path
R=Path('A:/Focus_Ux/hardware_revG')
G.showMainWindow();G.getMainWindow().hide()
d=A.openDocument(str(R/'mechanical/FOCUS_RevG_Standalone_Packaging_Study.FCStd'))
for o in d.Objects:
 if o.TypeId!='Part::Feature':continue
 o.ViewObject.Visibility=o.Category!='alternative';o.ViewObject.DisplayMode='Flat Lines'
 colors={'mechanical':(.15,.23,.27),'source':(.2,.55,.65),'nested':(.15,.5,.2),'reservation':(.75,.55,.2),'wire':(.9,.25,.15),'keepout':(.9,.15,.3),'thermal':(.2,.6,.9),'service':(.5,.3,.7)}
 o.ViewObject.ShapeColor=colors.get(o.Category,(.5,.5,.5))
 o.ViewObject.Transparency=75 if o.Category=='mechanical' else (85 if o.Category in ['reservation','keepout','service','thermal'] else 0)
v=G.activeDocument().activeView();v.setAnimationEnabled(False)
for n,fn in [('assembly',v.viewAxonometric),('top',v.viewTop),('front',v.viewFront)]:
 fn();G.updateGui();v.fitAll();G.updateGui();v.saveImage(str(R/'previews'/('RevG_'+n+'.png')),2000,1400,'White')
v.viewAxonometric();v.fitAll();d.save()
print('Rendered native RevG')
