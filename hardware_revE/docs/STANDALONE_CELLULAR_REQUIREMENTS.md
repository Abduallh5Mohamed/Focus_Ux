# Authoritative user requirement — standalone cellular glasses

Recorded2026-10-29. The human explicitly rejected using a phone in a pocket as the internet gateway and requested a dedicated physical Nano-SIM. This supersedes the phone/USB-host architecture as the intended product. Those paths may remain laboratory tools only; they do not satisfy the product requirement.

## Required product architecture

Camera+microphone → on-glasses acquisition/transport host → onboard LTE modem with dedicated Nano-SIM+antenna → external inference server → returned audio decoded/buffered on the device → limited driver → bone-conduction transducers.

Include an onboard rechargeable battery, protection, charger, regulated rails, supply-burst headroom, power control and measured thermal behavior. A SIM identifies the mobile subscription; it is not the radio modem, antenna, battery or video host. The product is standalone from a phone but remains dependent on cellular coverage and the inference server.

## Current implementation status

RevE CAD does NOT reserve or fit this full system. It is a superseded USB form study, not a cellular-glasses design. No LTE PCB, antenna, SIM socket, integrated battery or standalone A/V firmware has been implemented or tested. Do not add a SIM-looking slot to RevE and claim the requirement is met. Do not claim that ESP32-S3 supplies cellular connectivity or that a modem automatically replaces the A/V host.

## Sourced modem candidates, not frozen selections

- Quectel EG915U:23.6×19.9×2.4mm module, Cat1bis, advertised maxima10Mbps downlink/5Mbps uplink. Bare module size excludes carrierPCB, SIM holder, antenna, power circuit and acquisition host. Regional variant/operator support must be checked for intended deployment.
- SIMCom A7672:24×24×2.4mm, Cat1, advertised maxima10Mbps downlink/5Mbps uplink. Also a candidate only.

These are network maxima, not guaranteed mobile throughput or evidence that full camera streaming and low-delay audio are feasible. Choose Cat1bis versus a higher-throughput class only after measuring encoded A/V bitrate and application/network overhead under actual conditions. No carrier/band assumption or purchase approval is implied.

## Work required before the next enclosure revision

1. Fix the actual camera+microphone transport format, resolution/cadence, clocking and on-device host. The B0441 USB camera needs a compatible acquisition host; direct USB camera-to-SIM/modem wiring is not a functioning system. Host support for simultaneous capture, modem transport and returned audio must be demonstrated.
2. Measure compressed uplink bitrate, downlink audio, end-to-end latency/jitter and reconnection behavior using an LTE evaluation setup and a dedicated Nano-SIM. Bound stale-audio queues and implement stop/mute on loss. Server model latency remains a separate gate;4G does not establish realtime separation.
3. Select modem regional variant, actual Nano-SIM socket, host, antenna and driver with controlled drawings/reference circuits. Determine their real PCB area, mating/clearance volume and keepouts. Antenna placement near a head/frame requires RF design and appropriate assessment, not cosmetic concealment.
4. Measure average workload power and modem supply bursts before selecting a protected battery and charger. Runtime=usable battery energy divided by measured average system power; no battery capacity or runtime is committed yet. Check charge/use temperature, skin-facing surfaces and fault behavior.
5. Package the verified parts, then evaluate head weight/balance, fit, contact preload, cable/flex paths, strength and hinge motion. No enclosure location for the modem or battery is approved until this is done. Do not promise unchanged RevE thickness or comfort.

## Official sources

- https://www.quectel.com/product/lte-cat-1-bis-eg915u-series/
- https://quectel.com/content/uploads/2024/02/Quectel_EG915U_Series_Hardware_Design_V1.1.pdf (public older revision; current manufacturer page lists newer hardware design)
- https://en.simcom.com/product/A7672.html
