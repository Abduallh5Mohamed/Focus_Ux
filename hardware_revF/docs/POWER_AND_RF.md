# RevF cellular glasses — power, battery and RF engineering selection

Scope: proposed standalone acquisition/playback glasses with their own physical Nano-SIM and rechargeable battery. No phone is required as a network gateway. The current plan still uses an external server/GPU for Dolphin; cellular connectivity does **not** mean the model runs locally or that Internet latency is acceptable. No custom PCB, assembled pack, RF compliance or measured runtime is claimed by this document.

## Recommended battery decision

**Use a standard4.2V-charge high-discharge1S pack for the first prototype, assembled with protection by a competent battery-pack supplier.** Preferred cell candidate: Tattu500mAh1S95C3.7V, SKU `TAA5001S95JSL`, part `TA-95C-500-1S1P-L-JST` (store may appendTA7658). Maker brochure gives **58×18×8mm,14g**, nominal energy calculation1.85Wh. The maker lists the product for purchase, but stock/shipping to the actual build location are not verified. [Maker store](https://www.genstattu.com/1s-lipo-jst/), [official brochure](https://www.genstattu.com/content/instock/rc_product_brochure.pdf)

The95C marking suggests a high-discharge cell; it does **not** establish47.5A capability of the supplied connector, wiring, protection or final enclosure. No factory protection is stated in the reviewed maker listing. The installed JST-PHR lead must not be assumed adequate for a modem plus host. Require a pack supplier to confirm continuous/pulse current, connector and wire rating, DC resistance, temperature limits, charge specification and mechanical drawing. Do not solder directly to pouch cell tabs as an informal assembly step.

Protection candidate: BatterySpace product5080 `PCB-S1A6TH`, **33×5×2mm,0.45g**,5A maximum continuous,7–9A overcurrent trip, stated resistance≤40mΩ. Its NTC is for an **external monitor only**; the board does not itself disconnect on high temperature. It is a separate board, not proof the Tattu cell is already a protected pack. Low-voltage trip2.4V is an emergency backstop; system shutdown must occur earlier based on cell requirements and loaded-voltage characterization. Charge-overvoltage trip4.30V±0.05 is not a charger setpoint. [Supplier specifications](https://www.batteryspace.com/protection-circuit-module-pcb-for-3-7v-li-ion-battery-5-0a-limit-with-ntc-thermistor.aspx)

Reserve approximately **65×22×12mm internally** for a provisional cell+protection/wire/insulation compartment. This is an engineering allowance, not a battery manufacturer dimension or a frozen assembled-pack envelope. Pouch expansion clearance, bend radius, strain relief, abrasion/penetration protection, connector access and cell isolation must be defined with the pack supplier. Avoid a screw or clamp compressing the pouch. Cell14g+PCM0.45g excludes all wire/connector/insulation/support mass.

**Alternative, not baseline:** BETAFPV LAVA1S450mAh75C LiHV:61×15.5×6.7mm,12.2g,3.8Vnominal,1.71Wh, BT2.0. It is slim and purchasable from its maker but no built-in protection was verified. Its LiHV charge profile must be obtained explicitly; a4.35V full cell would exceed the modem's4.3V maximum operating supply if connected directly. Using a4.2V charger changes usable capacity, so the published energy cannot be assumed. Standard4.2V Tattu is selected to avoid mixing the chemistries in RevF. [BETAFPV official product](https://betafpv.com/products/lava-1s-450mah-75c-battery-4pcs)

A generic500mAh1C pack permits only0.5A by that rating. It is **not a substitute** for the selected high-discharge architecture. Two loose cells in parallel are not an approved way to fix the current budget; a dual-cell layout would require a qualified matched pack/protection/interconnect design.

## Power tree

```text
USB-C charging input → input protection/current advertisement handling
                         → BQ25895 charger + NVDC power path
Protected1S pack + temperature monitoring ↔ BAT/SYS power path
SYS → regulated3.8V modem rail, load switch + local RF/BB decoupling
    → regulated3.3V digital rail + ESP32-P4 reference power rails/sequencing
    → dedicated regulated5V USB camera/hub VBUS where required
    → low-noise codec/control rails + limited audio amplifier supply
```

The Nano-SIM slot and cellular antenna belong on the custom board/system. Modem USB is a data interface, **not a replacement for its VBAT power supply**. Camera/hub/modem USB enumeration and simultaneous operation must be demonstrated by the host stack before custom PCB routing is released. Do not backfeed external USB ports from the internal boost rail.

### Modem rail

**Baseline modem: SIMCom A7670E**,24×24×2.3mm, operating supply3.4–4.2V, typical3.8V. The published legacy A7670 hardware design calls for≥2A supply capability during maximum-power GSM transmit bursts. That is a supply design requirement, **not average LTE streaming current**. Exact purchase hardware/firmware revision still needs its matching latest manual; the SIMCom site lists several R2/R3/R5/R6 revisions. Keep voltage at module pins within its specific limits, and follow that manual's bulk/ceramic decoupling layout. Do not mistake the product table's few-milliamp low-power figure for video-streaming consumption. [Official SIMCom product/download listing](https://cn.simcom.com/product/A7670X.html)

Baseline selection is motivated by the parent team's documented Espressif USBmodem component listing testedA7670E support. This reduces software uncertainty but is not proof that our P4+hub+camera+firmware combination works. Confirm exact USB descriptors, interfaces, PPP support and simultaneous sustained streaming on the intended board. [Official Espressif esp_modem_usb_dte1.2.0 reference](https://components.espressif.com/components/espressif/esp_modem_usb_dte/versions/1.2.0/readme) (registry page could not be fetched by this research tool; parent integration verification remains necessary).

**Alternative only: QuectelEG915U**,23.6×19.9×2.4mm,3.3–4.3V operating supply, typical3.8V, maximum supply rating2.5A in the reviewed hardware design. Do not carry its2.5A/3.3V figures into A7670E tables or assume the same USBmodem driver integration. Keep its own variant/manual and additional integration work separate. [Official Quectel hardware design](https://quectel.com/content/uploads/2024/02/Quectel_EG915U_Series_Hardware_Design_V1.1.pdf)

A direct1S battery connection has no regulation margin near empty and no reliable immunity to pulse sag; RevF therefore proposes a buck-boost modem rail. **TPS55288** is an electrically plausible starting controller:2.7–36V input, adjustable output including3.8V,4.0×3.5mm IC package. Its16A headline is switch/inductor capability, **not a guaranteed16A output**, and its complete application needs external power components, compensation and thermal design. Use its reference design/EVM and power-stage calculations at actual worst-case battery voltage to qualify the baselineA7670E≥2A demand with margin. Supporting anEG915U substitution would require its own≥2.5A rail qualification; optional common3A design headroom is not either modem's average draw. Device package dimensions are not regulator solution dimensions. [TI TPS55288](https://www.ti.com/lit/ds/symlink/tps55288.pdf)

At3.0V battery and85% assumed efficiency, baselineA7670E3.8V×2A alone implies about**2.98A battery input**. The alternativeEG915U3.8V×2.5A would imply3.73A. These are distinct sizing examples, not measured operating points; host/camera/audio add more current. PCM5A, charger path, connector, traces and cable all need aggregate pulse/thermal validation. If their combined worst case exceeds the5A protection module, change the complete power design and pack; do not increase protection trip alone. A large capacitor cannot substitute for an undersized battery/path during sustained uplink.

### Charging and other rails

**BQ25895** is a candidate NVDC charger/power-path IC,4×4mm, with battery dischargeFET capability up to9A. It supports battery supplement and temperature supervision, but neither the9A figure nor its5A charging feature is a permission to charge this small cell at that rate. Its published default charge current is2.048A: **hold active-lowCE high in hardware until safe settings are written and verified**, including charge/precharge/termination currents, voltage, watchdog/reset behavior and NTC faults. A provisional low current such as0.25A is only a target pending the exact cell specification. Charging while worn should remain disabled in the first build. [TI BQ25895 datasheet](https://www.ti.com/lit/ds/symlink/bq25895.pdf)

For3.3V digital power, a buck alone cannot maintain regulation across a deeply discharged1S range; use a buck-boost or restrict the allowed battery/SYS range based on demonstrated dropout. The ESP32-P4 core/IO/memory rails and sequencing must follow its actual reference schematic, not an invented single3V3 input.5V camera/hub VBUS requires a separately budgeted boost converter with load switch/current limit. BQ25895OTG is not assumed simultaneously usable as an unrestricted second5V system converter while charging. Audio current and amplifier limiting must be included in the total; two1W-rated transducers do not require continuous2W playback.

## Runtime scenarios — not measurements

For a500mAh3.7Vnominal cell, nameplate energy is1.85Wh. Take **1.30Wh usable system energy as an illustrative combined derating** for conversion, shutdown reserve, load/temperature/aging and capacity uncertainty. This70% factor is an assumption, not verified efficiency; do not apply another efficiency factor to the same number without changing the definition.

| Assumed total average battery-side draw | Arithmetic runtime using1.30Wh |
|---:|---:|
|2W |39min |
|4W |19.5min |
|6W |13min |

These rows are **what-if scenarios**, not predicted streaming loads. We have no measured modem uplink duty cycle, encoder current, radio quality, amplifier use or server wait time. Do not advertise hours of continuous use from this slim cell. Poor coverage, retries, thermal limits and battery sag can shorten runtime or prevent useful operation. A practical all-day product would need a measured low-duty-cycle pipeline, substantially better energy budget or larger qualified pack geometry.

## Cellular RF candidate and physical integration

Candidate antenna: **TaoglasFXP40.07.0085A**, flexible element**42.6×12.1×0.15mm**,85mmØ1.13mm coax, I-PEX MHF-I/U.FL-compatible termination. Current officialPDF highlights700–960/1710–2200MHz. A7670E includesB7 in the current product listing, so this antenna's headline does **not** establish coverage of every supported modem band. Confirm the actual operator bands and exact antenna revision or select a genuinely suitable wider-band part. The maker website's wider frequency table differs from thePDF headline; do not resolve that discrepancy by assumption. [Official antennaPDF](https://www.taoglas.com/datasheets/FXP40.07.0085A.pdf)

Place it on a suitable plastic surface with the manufacturer's integration space, not directly on battery foil/ground/shield. Reserve coax bend/connector height and a50ΩRF feed/matching network on the customPCB. Keep camera clocks, USBHS, switching inductors and audio classD routing separated from RF. Near-head placement changes impedance/efficiency and requires final assembled-device tuning and radiated measurements. Module approvals, free-space antenna plots or a nominal CAD clearance do **not** establish SAR/head-use compliance. Nano-SIM ownership also does not establish operator certification, APN/data plan access or adequate uplink latency.

Real Nano-SIM connector candidate: **GCTSIM8051-6-0-14-00-A**,6contacts,push-pull,1.35mmprofile,no card-detect switch,without locating peg per ordering grid. Its official drawing must be imported for exact footprint/courtyard/cardtravel. This research verified height but did not unambiguously resolve every plan-view body/keepout annotation, so the parent CAD may reserve**16×15×3mm plus card insertion/removal travel** only as a provisional design space, not a manufacturer body dimension. A microSD socket is not electrically or mechanically interchangeable. Preserve1.8/3VSIM level compatibility and referenceESD/series-component recommendations. [GCT official drawing](https://gct.co/files/drawings/sim8051.pdf)

## Gates before calling this a functioning standalone prototype

1. Qualified protected pack drawing and current/thermal limits; verify actual connectors and polarity. Confirm charge chemistry before connecting charger.
2. Bench supply/electronic-load qualification of modem rail with burst loads and camera/host simultaneous load; scope at modem pins at low battery. Measure current through every bottleneck and inspect temperature.
3. Fault tests: charger reset/unprogrammed settings, missing/faultyNTC,USB attach/detach,low battery,modem brownout,short circuit and recovery. No unverified charging on a person's head.
4. Enumerate USB camera and modem concurrently through the intended hub; verify sustained data path, codec format and timestamps with bounded queues.
5. Register a physical Nano-SIM with the chosenA7670E revision/operator (or separately qualified alternative). Measure actual upload,server processing,downlink and playback delay under good/poor coverage; loss of connectivity must mute/stop stale audio.
6. Measure runtime and thermal map in the final enclosure. RF tuning and required head-worn regulatory testing precede any consumer/manufacturing claim.

## References archived

See `hardware_revF/reference/power/SOURCES.md`. Official Tattu brochure and Taoglas antennaPDF were archived locally for traceability. No physical battery or RF tests were performed.
