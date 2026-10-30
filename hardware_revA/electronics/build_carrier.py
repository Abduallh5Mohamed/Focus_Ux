"""Reproducible KiCad 10 carrier source generator; no external Python packages."""
from pathlib import Path
import pcbnew as p, uuid, json, csv
ROOT=Path(__file__).resolve().parent
LIB=Path('A:/Kicad/share/kicad/footprints')
def uid():return str(uuid.uuid4())
def xy(x,y):return p.VECTOR2I(p.FromMM(x),p.FromMM(y))
b=p.BOARD(); b.GetDesignSettings().SetBoardThickness(p.FromMM(1.6))
nets={}
for name in ['GND','SELECT_N','STOP_N','LED_DRIVE','LED_A']:
 n=p.NETINFO_ITEM(b,'/'+name);b.Add(n);nets[name]=n
components=[]
def fp(ref,value,lib,name,x,y,angle=0,pinmap={}):
 f=p.FootprintLoad(str(LIB/(lib+'.pretty')),name)
 if not f:raise RuntimeError(name)
 f.SetFPID(p.LIB_ID(lib,name))
 f.SetReference(ref);f.SetValue(value);f.SetOrientationDegrees(angle);f.SetPosition(xy(x,y))
 f.Reference().SetVisible(False);f.Value().SetVisible(False)
 for pad in f.Pads():
  if pad.GetNumber() in pinmap:pad.SetNet(nets[pinmap[pad.GetNumber()]])
  else:
   nc=p.NETINFO_ITEM(b,f'unconnected-({ref}-Pad{pad.GetNumber()})');b.Add(nc);pad.SetNet(nc)
 b.Add(f);components.append((ref,value,lib+':'+name,x,y,angle,pinmap));return f
j1=fp('J1','Pico physical pins 1-20 bottom row USB-left','Connector_PinSocket_2.54mm','PinSocket_1x20_P2.54mm_Vertical',8.37,24.89,90,{'3':'GND','4':'SELECT_N','5':'STOP_N','6':'LED_DRIVE'})
j2=fp('J2','Pico physical pins 40-21 top row USB-left','Connector_PinSocket_2.54mm','PinSocket_1x20_P2.54mm_Vertical',8.37,7.11,90)
j3=fp('J3','SELECT dry contact','Connector_PinHeader_2.54mm','PinHeader_1x02_P2.54mm_Vertical',61,8,0,{'1':'SELECT_N','2':'GND'})
j4=fp('J4','STOP dry contact','Connector_PinHeader_2.54mm','PinHeader_1x02_P2.54mm_Vertical',61,21.46,0,{'1':'STOP_N','2':'GND'})
d=fp('D1','Green LED 3mm','LED_THT','LED_D3.0mm',3,8,270,{'1':'GND','2':'LED_A'})
r=fp('R1','1k 1%','Resistor_THT','R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal',3,19,270,{'1':'LED_DRIVE','2':'LED_A'})
for i,(x,y) in enumerate([(3,3),(62,3),(3,29),(62,29)],1):
 f=p.FOOTPRINT(b);f.SetReference('H'+str(i));f.SetValue('NPTH2.4');f.SetPosition(xy(x,y));f.Reference().SetVisible(False);f.Value().SetVisible(False)
 f.SetAttributes(p.FP_BOARD_ONLY|p.FP_EXCLUDE_FROM_BOM|p.FP_EXCLUDE_FROM_POS_FILES)
 pad=p.PAD(f);pad.SetAttribute(p.PAD_ATTRIB_NPTH);pad.SetShape(p.PAD_SHAPE_CIRCLE);pad.SetSize(xy(2.4,2.4));pad.SetDrillSize(xy(2.4,2.4));pad.SetLayerSet(p.LSET.AllCuMask());f.Add(pad);b.Add(f)
for a,c in [((0,0),(65,0)),((65,0),(65,32)),((65,32),(0,32)),((0,32),(0,0))]:
 s=p.PCB_SHAPE();s.SetShape(p.SHAPE_T_SEGMENT);s.SetStart(xy(*a));s.SetEnd(xy(*c));s.SetLayer(p.Edge_Cuts);s.SetWidth(p.FromMM(.05));b.Add(s)
def track(net,layer,points):
 for a,c in zip(points,points[1:]):
  t=p.PCB_TRACK(b);t.SetStart(xy(*a));t.SetEnd(xy(*c));t.SetWidth(p.FromMM(.3));t.SetLayer(layer);t.SetNet(nets[net]);b.Add(t)
track('SELECT_N',p.F_Cu,[(15.99,24.89),(15.99,11),(56,11),(58,9),(61,8)])
track('STOP_N',p.F_Cu,[(18.53,24.89),(18.53,16),(60,16),(60,21.46),(61,21.46)])
track('LED_DRIVE',p.B_Cu,[(21.07,24.89),(21.07,14),(6,14),(3,19)])
track('LED_A',p.F_Cu,[(3,26.62),(1,26.62),(1,13),(3,10.54)])
track('GND',p.F_Cu,[(13.45,24.89),(13.45,21),(6,21),(5.5,20.5),(5.5,8),(3,8)])
track('GND',p.B_Cu,[(13.45,24.89),(13.45,28),(59,28),(59,12),(61,10.54)])
track('GND',p.B_Cu,[(59,24),(61,24)])
# Legible fabrication labels; keep assembly data out of crowded silk areas.
for text,x,y,size in [('FOCUS CTRL RevA',38,2,1),('PICO USB <',32,16,1.2),('SELECT',56,12,.8),('STOP',56,20,.8),('LED',4,15,.8)]:
 t=p.PCB_TEXT(b);t.SetText(text);t.SetPosition(xy(x,y));t.SetTextSize(xy(size,size));t.SetTextThickness(p.FromMM(.15));t.SetLayer(p.F_SilkS);b.Add(t)
p.SaveBoard(str(ROOT/'focus_control.kicad_pcb'),b)
# Independently match physical module pin coordinates to every carrier socket pad.
module=p.FootprintLoad(str(LIB/'Module.pretty'),'RaspberryPi_Pico_Common_THT')
module.SetOrientationDegrees(90);module.SetPosition(xy(8.37,24.89))
modulepins={int(q.GetNumber()):q.GetPosition() for q in module.Pads() if q.GetNumber().isdigit() and 1<=int(q.GetNumber())<=40}
orientation=[]
for socket in [j1,j2]:
 for pad in socket.Pads():
  physical=int(pad.GetNumber()) if socket==j1 else 41-int(pad.GetNumber())
  target=modulepins[physical];actual=pad.GetPosition()
  assert actual==target,(socket.GetReference(),pad.GetNumber(),physical,actual,target)
  orientation.append({'socket':socket.GetReference(),'socket_pin':int(pad.GetNumber()),'pico_physical_pin':physical,'x_mm':p.ToMM(actual.x),'y_mm':p.ToMM(actual.y)})
(ROOT/'physical_orientation_check.json').write_text(json.dumps({'result':'PASS','reference':'KiCad10 Module:RaspberryPi_Pico_Common_THT rotated+90deg,physical1 located8.37,24.89; official USB-top pinout independently inspected','verified_pins':40,'pin_coordinates':orientation},indent=2))
# Native schematic: self-contained passive symbols, every unused socket pin NC.
rootuuid=uid();symbols=[];instances=[]
for ref,value,foot,x,y,ang,pinmap in components:
 count=20 if ref in ['J1','J2'] else 2
 name='Header20' if count==20 else ('Resistor' if ref=='R1' else 'LED' if ref=='D1' else 'Header2')
 if name not in [v[0] for v in symbols]:
  pins=''.join(f'(pin passive line (at -7.62 {-i*2.54:.4f} 0)(length 2.54)(name "{i+1}" (effects(font(size 1 1))))(number "{i+1}"(effects(font(size 1 1)))))' for i in range(count))
  definition=f'(symbol "Focus:{name}" (pin_names(offset 0.5))(in_bom yes)(on_board yes)(property "Reference" "J"(at 0 5 0)(effects(font(size 1 1))))(property "Value" "{name}"(at 0 2.5 0)(effects(font(size 1 1))))(symbol "{name}_0_1"(rectangle(start -5.08 1.27)(end 5.08 {-((count-1)*2.54+1.27):.4f})(stroke(width .254)(type default))(fill(type background))))(symbol "{name}_1_1" {pins}))'
  symbols.append((name,definition))
 sx,sy={'J1':(40,40),'J2':(105,40),'J3':(165,40),'J4':(165,65),'R1':(165,95),'D1':(165,120)}[ref]
 sx,sy=round(sx/1.27)*1.27,round(sy/1.27)*1.27
 ident=uid()
 for f in b.GetFootprints():
  if f.GetReference()==ref:f.SetPath(p.KIID_PATH('/'+rootuuid+'/'+ident))
 instances.append(f'(symbol(lib_id "Focus:{name}")(at {sx} {sy} 0)(unit 1)(in_bom yes)(on_board yes)(dnp no)(uuid "{ident}")(property "Reference" "{ref}"(at {sx+8} {sy-4} 0)(effects(font(size 1.27 1.27))))(property "Value" "{value}"(at {sx+8} {sy-1} 0)(effects(font(size 1 1))))(property "Footprint" "{foot}"(at {sx} {sy} 0)(effects(font(size 1 1))(hide yes)))'+''.join(f'(pin "{i+1}"(uuid "{uid()}"))' for i in range(count))+f'(instances(project "focus_control"(path "/{rootuuid}"(reference "{ref}")(unit 1)))))')
 for i in range(count):
  px,py=sx-7.62,sy+i*2.54; net=pinmap.get(str(i+1))
  if net:
   instances.append(f'(label "{net}"(at {px} {py} 0)(effects(font(size 1 1))(justify right bottom))(uuid "{uid()}"))')
  else:instances.append(f'(no_connect(at {px} {py})(uuid "{uid()}"))')
texts=[('FOCUS wired control carrier - engineering prototype',30,20),('Pico H fits J1/J2; USB powers ONLY Pico. Camera USB goes directly to host.',30,25),('J1 socket pin n = Pico pin n. J2 socket pin n = Pico pin (41-n).',30,105),('GP2 select; GP3 stop/mute; internal pullups required. Dry contacts to GND.',30,112),('GP4 -> R1 -> LED anode. D1 pin1 cathode, pin2 anode.',30,119),('Unused Pico pins intentionally not connected. No battery, radio or audio path on carrier.',30,126),('J3/J4 connect normally-open OFFBOARD switches. Module not soldered to carrier.',30,133)]
for text,x,y in texts:instances.append(f'(text "{text}"(at {x} {y} 0)(effects(font(size 1.1 1.1))(justify left))(uuid "{uid()}"))')
sch=f'(kicad_sch(version 20250114)(generator "focus_carrier_generator")(uuid "{rootuuid}")(paper "A4")(lib_symbols '+''.join(s[1] for s in symbols)+')'+''.join(instances)+')'
(ROOT/'focus_control.kicad_sch').write_text(sch,encoding='utf-8')
(ROOT/'Focus.kicad_sym').write_text('(kicad_symbol_lib(version 20250114)(generator "focus_carrier_generator")'+''.join(s[1].replace('(symbol "Focus:', '(symbol "') for s in symbols)+')')
(ROOT/'sym-lib-table').write_text('(sym_lib_table\n  (version 7)\n  (lib (name "Focus") (type "KiCad") (uri "${KIPRJMOD}/Focus.kicad_sym") (options "") (descr "Local carrier schematic symbols"))\n)\n')
(ROOT/'placement.json').write_text(json.dumps([{'reference':q[0],'value':q[1],'footprint':q[2],'x_mm':q[3],'y_mm':q[4],'rotation_deg':q[5],'net_mapping':q[6]} for q in components],indent=2))
(ROOT/'focus_control.kicad_pro').write_text('{}')
p.SaveBoard(str(ROOT/'focus_control.kicad_pcb'),b)
print('Created native schematic and routed PCB')
