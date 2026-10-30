"""Generate review-only RevG subsystem schematic FIRST, then placement-only PCB.
Run with A:/Kicad/bin/python.exe. No fabrication export. Never touches prior revisions.
"""
from pathlib import Path
import uuid,json,csv
import pcbnew as p
R=Path(__file__).resolve().parent
LIB=Path('A:/Kicad/share/kicad/footprints')
def uid(): return str(uuid.uuid4())
def quote(s): return str(s).replace('\\','\\\\').replace('"','\\"')
def xy(x,y): return p.VECTOR2I(p.FromMM(x),p.FromMM(y))
root=uid(); defs={}; comps=[]
def add(ref,value,pins,nets,foot,loc,mpn='UNSELECTED',source='',notes=''):
    name=ref
    types={'P':'passive','I':'input','O':'tri_state','W':'power_in','B':'bidirectional'}
    spec=''.join(f'(pin {types[t]} line(at -12.7 {-i*2.54} 0)(length 2.54)(name "{quote(n)}"(effects(font(size 1 1))))(number "{num}"(effects(font(size 1 1)))))' for i,(num,n,t) in enumerate(pins))
    defs[name]=f'(symbol "RevG:{name}"(pin_names(offset 0.5))(in_bom yes)(on_board yes)(property "Reference" "{ref}"(at 0 5 0)(effects(font(size 1 1))))(property "Value" "{quote(value)}"(at 0 2.5 0)(effects(font(size 1 1))))(symbol "{name}_0_1"(rectangle(start -10.16 1.27)(end 15.24 {-len(pins)*2.54+1.27})(stroke(width 0.254)(type default))(fill(type background))))(symbol "{name}_1_1" {spec}))'
    comps.append(dict(ref=ref,value=value,pins=pins,nets=nets,foot=foot,loc=loc,mpn=mpn,source=source,notes=notes,id=uid()))
def hdr(ref,label,nets,loc):
    add(ref,label,[(str(i+1),n,'P') for i,n in enumerate(nets)],dict((str(i+1),n) for i,n in enumerate(nets)),f'Connector_PinHeader_2.54mm:PinHeader_1x{len(nets):02d}_P2.54mm_Vertical',loc,notes='Bench header; production connector MPN and current rating unresolved')
def passive(ref,value,a,b,loc,cap=False):
    add(ref,value,[('1','1','P'),('2','2','P')],{'1':a,'2':b},'Capacitor_SMD:C_0603_1608Metric' if cap else 'Resistor_SMD:R_0603_1608Metric',loc,notes='Value specified; manufacturer MPN/tolerance procurement OPEN')
micurl='https://www.infineon.com/assets/row/public/documents/24/49/infineon-im69d130-datasheet-en.pdf'
ampurl='https://www.ti.com/lit/ds/symlink/tpa2016d2.pdf'
hdr('J1','P4 PDM host OPEN GPIO map',['MIC_3V3','GND','PDM_CLK_HOST','PDM_D01','PDM_D23'],(50,45))
passive('R1','33R clock damping candidate','PDM_CLK_HOST','PDM_CLK',(125,45))
for i in range(4):
    add('MK'+str(i+1),'IM69D130 4x3x1.2 mm',[('1','DATA','O'),('2','VDD','W'),('3','CLOCK','I'),('4','SELECT','I'),('5','GND','W')],{'1':'PDM_D01' if i<2 else 'PDM_D23','2':'MIC_3V3','3':'PDM_CLK','4':'GND' if i%2==0 else 'MIC_3V3','5':'GND'},'Sensor_Audio:Infineon_PG-LLGA-5-1',(50+i*90,85),'IM69D130V01XTSA1',micurl,'Common clock; opposite SELECT within each data pair; bottom acoustic port MUST remain clear')
    passive('C'+str(i+1),'100nF X7R 10V','MIC_3V3','GND',(50+i*90,120),True)
hdr('J2','External regulated AMP rail 3.0V',['AMP_3V0','GND'],(50,160))
hdr('J3','External DAC differential analog',['DAC_LP','DAC_LN','DAC_RP','DAC_RN','GND'],(140,160))
hdr('J4','Host control 3V3; watchdog OPEN',['CTRL_3V3','GND','SCL','SDA','HOST_AUDIO_ENABLE'],(230,160))
pins=[('1','INL+','I'),('2','INL-','I'),('3','AGND','W'),('4','PVDDL','W'),('5','PVDDL','W'),('6','OUTL+','O'),('7','OUTL-','O'),('8','PGND','W'),('9','OUTR-','O'),('10','OUTR+','O'),('11','PVDDR','W'),('12','PVDDR','W'),('13','AVDD','W'),('14','INR-','I'),('15','INR+','I'),('16','REVIEW_UNSPECIFIED','P'),('17','SCL','I'),('18','SDZ','I'),('19','SDA','B'),('20','REVIEW_UNSPECIFIED','P'),('21','EP_VERIFY_PAD','W')]
mapping={'1':'IN_LP','2':'IN_LN','3':'GND','4':'AMP_3V0','5':'AMP_3V0','6':'OUT_LP','7':'OUT_LN','8':'GND','9':'OUT_RN','10':'OUT_RP','11':'AMP_3V0','12':'AMP_3V0','13':'AMP_3V0','14':'IN_RN','15':'IN_RP','17':'SCL','18':'AMP_SDZ','19':'SDA','21':'GND'}
add('U1','TPA2016D2RTJR REVIEW RTJ pad drawing',pins,mapping,'Package_DFN_QFN:QFN-20-1EP_4x4mm_P0.5mm_EP2.5x2.5mm',(410,160),'TPA2016D2RTJR',ampurl,'Pins16/20 unresolved and intentionally OPEN. EP footprint provisional pending RTJ manufacturer land pattern; NOT RELEASED')
for i,ch in enumerate(['LP','LN','RP','RN']):
    passive('R'+str(10+i*2),'100k 1% attenuation','DAC_'+ch,'ATT_'+ch,(50+i*90,240))
    passive('R'+str(11+i*2),'1k 1% attenuation','ATT_'+ch,'GND',(50+i*90,265))
    passive('C'+str(10+i),'1uF X7R 10V AC coupling','ATT_'+ch,'IN_'+ch,(50+i*90,290),True)
for i,val in enumerate(['10uF X7R 10V','100nF X7R 10V','100nF X7R 10V']):
    passive('C'+str(20+i),val,'AMP_3V0','GND',(50+i*90,330),True)
passive('R20','4k7 candidate I2C pullup','CTRL_3V3','SCL',(320,330))
passive('R21','4k7 candidate I2C pullup','CTRL_3V3','SDA',(410,330))
passive('R22','10k host enable isolation','HOST_AUDIO_ENABLE','AMP_SDZ',(50,375))
passive('R23','47k DEFAULT MUTE pulldown','AMP_SDZ','GND',(140,375))
hdr('J5','HARD MUTE dry-contact switch',['AMP_SDZ','GND'],(230,375))
hdr('J6','EXTERNAL open drain supervisor',['AMP_SDZ','GND'],(320,375))
hdr('J7','Left BTL floating pair',['OUT_LP','OUT_LN'],(500,175))
hdr('J8','Right BTL floating pair',['OUT_RP','OUT_RN'],(500,205))
for i,n in enumerate(['MIC_3V3','PDM_CLK','PDM_D01','PDM_D23','AMP_3V0','AMP_SDZ','GND']):
    add('TP'+str(i+1),n,[('1','TEST','P')],{'1':n},'TestPoint:TestPoint_Pad_D1.0mm',(50+i*70,425),notes='Probe pad; test instrument loading must be considered')
items=[]
for c in comps:
    x,y=c['loc'];ref=c['ref'];ident=c['id']
    props=''.join(f'(property "{k}" "{quote(v)}"(at {x+18} {y-5+j*2.54} 0)(effects(font(size 1 1)){"(hide yes)" if j>1 else ""}))' for j,(k,v) in enumerate([('Reference',ref),('Value',c['value']),('Footprint',c['foot']),('MPN',c['mpn']),('Datasheet',c['source']),('Review',c['notes'])]))
    items.append(f'(symbol(lib_id "RevG:{ref}")(at {x} {y} 0)(unit 1)(in_bom yes)(on_board yes)(dnp no)(uuid "{ident}"){props}'+''.join(f'(pin "{n}"(uuid "{uid()}"))' for n,_,_ in c['pins'])+f'(instances(project "FOCUS_RevG_Mainboard_REVIEW"(path "/{root}"(reference "{ref}")(unit 1)))))')
    for i,(n,_,_) in enumerate(c['pins']):
        if n in c['nets']:
            items.append(f'(label "{c["nets"][n]}"(at {x-12.7} {y+i*2.54} 0)(effects(font(size 0.9 0.9))(justify right bottom))(uuid "{uid()}"))')
def note(text,x,y,size=1.5):items.append(f'(text "{quote(text)}"(at {x} {y} 0)(effects(font(size {size} {size}))(justify left))(uuid "{uid()}"))')
note('FOCUS RevG MAINBOARD REVIEW - PARTIAL SUBSYSTEM SCHEMATIC ONLY',25,15,2.5)
note('Four-mic PDM + analog amplifier only. Host / USB / LTE / SIM / charger / battery / regulators / DAC / watchdog / independent limiter NOT implemented.',25,23)
note('NO FABRICATION RELEASE. P4 GPIO map open. Power sources are external lab supplies. Unresolved pins are deliberately open; ERC is not forced clean.',25,30)
note('Default mute: R23 pulls SDZ low. External switch J5 shorts SDZ to GND regardless of host. J6 watchdog hardware is REQUIRED but not designed.',25,465)
note('100k/1k input attenuation is a provisional fixed gain bound, NOT a certified independent limiter. DAC range, max gain, transient and output tests remain OPEN.',25,475)
note('BTL: OUT_LN and OUT_RN are active outputs. Never tie to ground or each other. Dummy loads only until output and contact calibration.',25,485)
note('USB topology proposal: P4 USB-HS HOST -> powered USB2512B hub -> B0441 UVC camera + A7670E USB modem. Separate modem VBAT supply.',25,500)
note('Power proposal: USB-C protection -> charger/power path <-> protected 1S pack+NTC -> 3.8V modem / host rails / 5V VBUS / audio rail. Not drawn circuitry.',25,510)
name='FOCUS_RevG_Mainboard_REVIEW'
(R/(name+'.kicad_sch')).write_text(f'(kicad_sch(version 20250114)(generator "focus_revg_review")(uuid "{root}")(paper "A1")(lib_symbols '+''.join(defs.values())+')'+''.join(items)+')')
(R/'RevG.kicad_sym').write_text('(kicad_symbol_lib(version 20250114)(generator "focus_revg_review")'+''.join(v.replace('(symbol "RevG:', '(symbol "') for v in defs.values())+')')
(R/'sym-lib-table').write_text('(sym_lib_table\n  (version 7)\n  (lib (name "RevG") (type "KiCad") (uri "${KIPRJMOD}/RevG.kicad_sym") (options "") (descr "Typed review symbols; explicit unresolved pins"))\n)\n')
(R/(name+'.kicad_pro')).write_text('{}')
# PCB intentionally AFTER completed available schematic; placement review only.
b=p.BOARD();b.GetDesignSettings().SetBoardThickness(p.FromMM(1.6));nets={}
for c in comps:
    for net in c['nets'].values():
        if net not in nets: nets[net]=p.NETINFO_ITEM(b,'/'+net);b.Add(nets[net])
for i,c in enumerate(comps):
    lib,foot=c['foot'].split(':');f=p.FootprintLoad(str(LIB/(lib+'.pretty')),foot)
    if not f:raise RuntimeError(c['foot'])
    f.SetFPID(p.LIB_ID(lib,foot));f.SetReference(c['ref']);f.SetValue(c['value']);f.SetPosition(xy(15+(i%9)*22,15+(i//9)*25));f.SetPath(p.KIID_PATH('/'+root+'/'+c['id']))
    f.Reference().SetVisible(True);f.Value().SetVisible(False)
    for pad in f.Pads():
        if pad.GetNumber() in c['nets']:pad.SetNet(nets[c['nets'][pad.GetNumber()]])
    b.Add(f)
for a,z in [((0,0),(210,0)),((210,0),(210,180)),((210,180),(0,180)),((0,180),(0,0))]:
    s=p.PCB_SHAPE();s.SetShape(p.SHAPE_T_SEGMENT);s.SetStart(xy(*a));s.SetEnd(xy(*z));s.SetLayer(p.Edge_Cuts);s.SetWidth(p.FromMM(.05));b.Add(s)
t=p.PCB_TEXT(b);t.SetText('RevG SUBSYSTEM PLACEMENT ONLY - UNROUTED - NO FAB');t.SetPosition(xy(105,172));t.SetTextSize(xy(1.5,1.5));t.SetLayer(p.F_SilkS);b.Add(t)
p.SaveBoard(str(R/(name+'.kicad_pcb')),b)
(R/'design_manifest.json').write_text(json.dumps({'status':'PARTIAL_SUBSYSTEM_SCHEMATIC_UNROUTED_PCB_NOT_MAINBOARD_COMPLETE','board_mm':[210,180,1.6],'board_size_purpose':'bench review page, NOT wearable board envelope','components':comps},indent=2))
with (R/'subsystem_components.csv').open('w',newline='') as f:
    w=csv.writer(f);w.writerow(['Reference','Value','MPN','Footprint','Datasheet','Review'])
    for c in comps:w.writerow([c[k] for k in ['ref','value','mpn','foot','source','notes']])
print(f'Created schematic first, then UNROUTED PCB: {len(comps)} components; no Gerbers')
