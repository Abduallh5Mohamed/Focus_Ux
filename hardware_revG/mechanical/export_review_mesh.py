"""Export current native RevG geometry triangles for deterministic review renders.

Run with FreeCADCmd. This does not edit CAD or establish manufacturing readiness.
"""
import FreeCAD as App
import json
import sys
from pathlib import Path

variant = len(sys.argv)>1 and sys.argv[1]=='compact'
root=Path('A:/Focus_Ux/hardware_revG/mechanical')/('compact_direction' if variant else '')
doc=App.openDocument(str(root/('FOCUS_RevG_Compact_Packaging_Screen.FCStd' if variant else 'FOCUS_RevG_Standalone_Packaging_Study.FCStd')))
meshes=[]
for obj in doc.Objects:
    if obj.TypeId!='Part::Feature' or obj.Category in ('alternative','service','thermal'):
        continue
    verts,faces=obj.Shape.tessellate(1.0)
    meshes.append({'name':obj.Name,'category':obj.Category,
                   'vertices':[[v.x,v.y,v.z] for v in verts],
                   'faces':faces})
(root/'review_mesh.json').write_text(json.dumps(meshes,separators=(',',':')),encoding='utf-8')
print('Exported',len(meshes),'CAD bodies and reservations')
