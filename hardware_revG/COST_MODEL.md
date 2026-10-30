# FOCUS RevG — cost and retail feasibility model, Egypt

Date2026-10-30. User targets: EGP12,000–18,000 retail, first10–20 engineering units then100-unit pilot. All values below except explicitly cited single-unit camera price are **scenario inputs, not supplier quotes or customer prices**. `BOM.csv` has UNKNOWN for unquoted parts. No economically defensible fixed COGS exists until complete circuitry, pack, case, assembly and regulatory scope are quoted.

## Formula and assumptions

For quantity Q:

```text
Hardware_EGP = USD_BOM(Q) × FX_EGP_per_USD × (1 + import_and_freight_fraction)
Fully_loaded_unit = Hardware_EGP + assembly_and_test_EGP(Q)
                  + packaging_warranty_distribution_EGP(Q) + NRE_and_tooling_EGP / Q
Retail_ex_VAT = Retail_incl_VAT / (1 + assumed_VAT_rate)
Unit_contribution = Retail_ex_VAT - Fully_loaded_unit - variable_sales_support_EGP
```

Do not double-count freight/tax already included in supplier quotes. The [Egyptian Tax Authority](https://www.eta.gov.eg/sites/default/files/2024-02/VAT-Executive-Regulations-English.pdf) describes a standard VAT rate of14%; actual classification, registration, crediting and any special treatment for this product must be checked by an Egyptian professional. No medical-device exemption assumed. Import/customs duty and customs valuation are unknown until product classification and origin are fixed.

Baseline illustration only: FX55 EGP/USD (assumption, **not current market rate**),20% combined import/freight contingency (assumption),14% VAT modeling rate, one-time NRE/tooling300,000EGP (assumption), plus the table below. This is a sensitivity example to expose the unit-economics burden; it is not an assembled-device quotation.

| Quantity | Assumed USD hardware BOM | Hardware×FX×1.20 EGP | Assembly/test + package/warranty/distribution EGP | NRE/Q EGP | Illustrative fully-loaded EGP |
|---:|---:|---:|---:|---:|---:|
| 10 engineering | 180 | 11,880 | 5,000 | 30,000 | 46,880 |
| 20 engineering | 160 | 10,560 | 4,000 | 15,000 | 29,560 |
| 100 pilot | 100 | 6,600 | 2,500 | 3,000 | 12,100 |
| 500 | 85 | 5,610 | 2,000 | 600 | 8,210 |
| 1000 | 75 | 4,950 | 1,600 | 300 | 6,850 |

These BOM decreases with volume are **hypothetical**, and the unknown protected battery, mainboard fabrication, lenses/hinges, RF validation and factory test can move costs upward. Early engineering prototypes are not intended to match retail price. For100 units, illustrative retailEGP12,000 corresponds to ~10,526 ex-VAT, EGP18,000 to ~15,789 ex-VAT. Against the illustrative EGP12,100 loaded unit, contribution ranges from -1,574 to3,689EGP BEFORE variable sales support and recurring cloud/data. The lower retail bound therefore fails this scenario; the upper may still be unattractive after support/returns. An NRE/tooling bill above300k or hardware above100USD worsens it.

Illustrative unit budget at100 with25% gross margin target BEFORE variable sales support: maximum fully loaded cost is approximately EGP7,895 at EGP12k retail and EGP11,842 at EGP18k retail under the14% VAT model. Those are financial gates, not product feasibility evidence. Cost cuts cannot remove four synchronized microphones, pack protection, hardware audio mute, safe charger or RF matching if required for function/safety.

## Quoted evidence actually available

- [Arducam B0441 manufacturer listing](https://www.arducam.com/5mp-autofocus-usb-camera-module-with-single-microphone-for-windows-linux-macos-android.html) displayed USD34.99 for one unit when checked2026-10-30; that is a **single-unit module price**, not a100-unit quote. Its full USB board may be inappropriate cost/energy/size for production even if good for the bench.
- [TI TPA2016D2 purchasing page](https://www.ti.com/product/TPA2016D2/part-details/TPA2016D2RTJT) showed no price and out-of-stock for the displayed variant when checked; alternates and distribution availability need procurement verification. No fabricated price appears in BOM.
- [Raspberry Pi CM5 launch announcement](https://www.raspberrypi.com/news/compute-module-5-on-sale-now/) cited a launch base fromUSD45, but that historical price is not a current quote and CM5 is a bench comparison, quantity0 in the wearable BOM.

## Recurring cost separate from the device

For each active user-month: `LTE_data_GB × operator_tariff_EGP_per_GB + server_gpu_seconds × effective_EGP_per_second + storage/transit/support`. No data contract or server quote exists. Illustrative raw PCM four channels at16kHz×16bit = **1.024 Mbit/s before overhead**; compressed/multiplexed uplink and occasional camera must be measured. Do not turn a modem maximum data rate into expected billing or latency. At1.024Mbit/s continuously for2h, one session produces about0.92GB decimal data before network overhead; this is only an uncompressed reference, not planned data usage. Codec and duty cycle affect both cost and model quality.

## Quotation plan

For10/20/100/500/1000 units, obtain distributor/factory quotes dated with currency, MOQ and exact SKU/revision for: modules, 4 matched mics, antenna, pack/PCM/charger, driver/transducers, PCB stackup and assembly, optical frame/lenses/hinges, packaging, functional test fixture, rework/yield, logistics and warranty. Obtain two Egyptian operator data plans and model server concurrency/availability at measured latency. Store all quote links/currencies/dates in BOM.csv; calculate FX at the actual settlement rate. Separate NRE, certification and tooling from recurring COGS; negotiate only after hardware gates and intended-use classification.
