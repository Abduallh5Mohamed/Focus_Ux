"""Orthographic previews drawn from actual native FreeCAD tessellation.

Requires Pillow. These are review views, not toleranced manufacturing drawings.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import json, math
import sys

root=Path('A:/Focus_Ux/hardware_revG')
variant = len(sys.argv)>1 and sys.argv[1]=='compact'
meshdir=root/'mechanical'/('compact_direction' if variant else '')
meshes=json.loads((meshdir/'review_mesh.json').read_text(encoding='utf-8'))
colors={'mechanical':(37,45,50),'source':(60,130,155),'nested':(66,141,107),
        'reservation':(192,139,61),'wire':(212,85,72),'keepout':(195,65,75)}

def render(name,ax1,ax2,depth,width=1800,height=1180):
    # Project positions with exact orthographic CAD coordinates. Camera light is
    # fixed in image space; ordering is by projected camera depth.
    tris=[];bounds=[]
    for obj in meshes:
        vs=obj['vertices']
        coords=[(sum(p[i]*ax1[i] for i in range(3)),sum(p[i]*ax2[i] for i in range(3)),sum(p[i]*depth[i] for i in range(3))) for p in vs]
        if obj['category'] in ('mechanical','source','nested'):
            bounds.extend((x,y) for x,y,_ in coords)
        for a,b,c in obj['faces']:
            p,q,r=coords[a],coords[b],coords[c]
            if abs((q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0]))<.05:continue
            tris.append((sum(v[2] for v in (p,q,r))/3,obj['category'],[(v[0],v[1]) for v in (p,q,r)]))
    minx=min(x for x,y in bounds);maxx=max(x for x,y in bounds)
    miny=min(y for x,y in bounds);maxy=max(y for x,y in bounds)
    scale=min((width-180)/(maxx-minx),(height-220)/(maxy-miny));cx=(minx+maxx)/2;cy=(miny+maxy)/2
    im=Image.new('RGB',(width,height),(239,242,242));d=ImageDraw.Draw(im)
    # Far to near painter order. Transparent reserved volumes are shown as outlines.
    for z,cat,poly in sorted(tris,key=lambda t:t[0]):
        pts=[(round(width/2+(x-cx)*scale),round(height/2-(y-cy)*scale+35)) for x,y in poly]
        color=colors.get(cat,(90,90,90))
        if cat in ('reservation','wire','keepout'):
            d.line(pts+[pts[0]],fill=color,width=1)
        else:
            d.polygon(pts,fill=color)
            d.line(pts+[pts[0]],fill=tuple(max(0,int(c*.55)) for c in color),width=1)
    d.text((60,45),f'FOCUS RevG {"COMPACT" if variant else "BASELINE"} - {name.upper()} / CAD SCREENING',fill=(22,30,35),font=ImageFont.load_default(size=30))
    d.text((60,height-65),'Native CAD mesh projection. Component colors mark sourced or provisional volumes. Not a physical prototype.',fill=(58,66,72),font=ImageFont.load_default(size=18))
    path=root/'previews'/f'RevG_{"Compact_CAD" if variant else "CAD"}_{name}.png';path.parent.mkdir(exist_ok=True)
    im.save(path)
    return str(path)

if __name__=='__main__':
    print(render('front',(1,0,0),(0,0,1),(0,1,0)))
    print(render('top',(1,0,0),(0,1,0),(0,0,1)))
    k=1/math.sqrt(2);q=1/math.sqrt(6)
    print(render('isometric',(k,-k,0),(q,q,2*q),(-q,-q,q)))
