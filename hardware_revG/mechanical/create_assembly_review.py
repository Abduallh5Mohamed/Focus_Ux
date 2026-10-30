"""Self-contained review sheet from compact native-CAD projections.

Dimensions are screening extents, not manufacturing tolerances.
"""
from pathlib import Path
import base64

root = Path('A:/Focus_Ux/hardware_revG')
preview = root/'previews'
out = root/'mechanical'/'compact_direction'/'RevG_assembly_review.svg'

def embed(name):
    data = base64.b64encode((preview/f'RevG_Compact_CAD_{name}.png').read_bytes()).decode()
    return f'data:image/png;base64,{data}'

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="2260" viewBox="0 0 1800 2260">
<style>
  text {{font-family:Arial,sans-serif;fill:#14252d}}
  .title {{font-size:54px;font-weight:700}}
  .sub {{font-size:28px;fill:#52636b}}
  .label {{font-size:32px;font-weight:700}}
  .dim {{font-size:30px;fill:#007f92;font-weight:700}}
  .note {{font-size:26px;fill:#43545b}}
  .line {{stroke:#008aa1;stroke-width:3;fill:none}}
</style>
<rect width="1800" height="2260" fill="#f8faf9"/>
<text x="70" y="86" class="title">FOCUS / RevG compact shell review</text>
<text x="70" y="132" class="sub">Original everyday-glasses direction · native FreeCAD solid projections · 2026-10-30</text>
<line x1="70" y1="158" x2="1730" y2="158" stroke="#c5d3d4" stroke-width="3"/>
<text x="70" y="218" class="label">TOP / component packaging</text>
<image x="70" y="242" width="1660" height="1088" href="{embed('top')}"/>
<line x1="195" y1="1360" x2="1605" y2="1360" class="line"/>
<path d="M195 1348v24 M1605 1348v24" class="line"/>
<text x="790" y="1352" class="dim">202 mm overall X envelope</text>
<text x="70" y="1425" class="label">FRONT / lens and camera bar</text>
<image x="70" y="1445" width="820" height="538" href="{embed('front')}"/>
<text x="930" y="1425" class="label">ISOMETRIC / assembled screening</text>
<image x="930" y="1445" width="800" height="524" href="{embed('isometric')}"/>
<text x="70" y="2050" class="dim">156 mm Y length · 51 mm Z full envelope · 158 mm front brow span</text>
<text x="70" y="2100" class="note">Provisional cavities: left power/pack; right host/LTE/SIM; 4 mic allowances; 2 BC contacts.</text>
<text x="70" y="2145" class="note">Partial assumed mass 90.51 g. 16 sampled folding failures. RF antenna fit failed.</text>
<text x="70" y="2190" class="note">Review drawing only: lens fit, fasteners, tolerances, battery runtime, heat and RF unverified.</text>
</svg>'''
out.write_text(svg, encoding='utf-8')
print(out)
