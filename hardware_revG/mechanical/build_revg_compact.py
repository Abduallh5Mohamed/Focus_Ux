"""Compact RevG shell screening variant, derived from build_revg.py.

This changes only shell extents. It does not close component, power or RF gaps.
The baseline RevG study remains available as separate evidence.
"""
from pathlib import Path

source = Path(__file__).with_name('build_revg.py').read_text()
source = source.replace("O=R/'mechanical'", "O=R/'mechanical'/'compact_direction'; O.mkdir(exist_ok=True)")
source = source.replace("A.newDocument('FOCUS_RevG_Standalone_Packaging_Study')", "A.newDocument('FOCUS_RevG_Compact_Packaging_Screen')")
source = source.replace("box(-31.4,-7,21.6,62.8,7.4,9.8)", "box(3.6,-7,21.6,62.8,7.4,9.8)")
source = source.replace("V(0,-11,26),V(0,1,0)", "V(55,-11,26),V(0,1,0)")
source = source.replace("box(-31,-6.6,22,62,6,9)", "box(4,-6.6,22,62,6,9)")
source = source.replace("('FR',60,-7,27)", "('FR',72,-7,27)")
source = source.replace("x=-99 if sgn<0 else 68;w=31 if sgn<0 else 38", "x=-97 if sgn<0 else 71;w=28 if sgn<0 else 34")
source = source.replace("outer=rounded(x,8,8,w,139,23,4)", "outer=rounded(x,8,9,w,139,19,4)")
source = source.replace("cavity=rounded(x+1.5,9.5,9.5,w-3,136,23,3)", "cavity=rounded(x+1.5,9.5,10.5,w-3,136,18,3)")
source = source.replace(
    "shell=outer.cut(cavity)",
    "shell=outer.cut(cavity)\n"
    " shell=shell.cut(Part.makeCylinder(.9,131,V(-70.7 if sgn<0 else 70.7,12,27),V(0,1,0)))\n"
    " shell=shell.cut(box(-96.3 if sgn<0 else 96.7,59.7,25.7,4.6,4.6,3))",
)
source = source.replace("rounded(x,8,31.3,w,139,1.2,4)", "rounded(x,8,28.3,w,139,1.2,4)")
source = source.replace("FOCUS_RevG_Standalone_Packaging_Study.FCStd", "FOCUS_RevG_Compact_Packaging_Screen.FCStd")
source = source.replace("FOCUS_RevG_Standalone_Packaging_Study.step", "FOCUS_RevG_Compact_Packaging_Screen.step")
source = source.replace("'revision':'G engineering packaging study'", "'revision':'G compact shell direction screening; still not wearable validated'")
source = source.replace("'mass_scope':'polymer", "'mass_scope':'compact screen; polymer")
exec(compile(source, str(Path(__file__).with_name('build_revg.py')), 'exec'))
