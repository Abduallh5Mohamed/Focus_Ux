"""FOCUS Pico H control bring-up. MicroPython; unflashed/unverified on hardware.
GPIO2/3 are internal-pullup dry-contact inputs. GPIO4 drives board LED via1k.
STOP_REQUESTED does not disconnect audio. Host must handle events explicitly.
"""
from machine import Pin
import time
import sys
import select
import json

led = Pin(4, Pin.OUT, value=0)
inputs = {"SELECT_REQUESTED": Pin(2, Pin.IN, Pin.PULL_UP),
          "STOP_REQUESTED": Pin(3, Pin.IN, Pin.PULL_UP)}
stable = {name: pin.value() for name, pin in inputs.items()}
last = dict(stable)
changed = {name: time.ticks_ms() for name in inputs}
sequence = 0
poller = select.poll()
poller.register(sys.stdin, select.POLLIN)
buffer = ""

def emit(name):
    global sequence
    sequence += 1
    print(json.dumps({"protocol":"focus-controls-v1", "event":name,
                      "seq":sequence, "device_ms":time.ticks_ms()}))

emit("BOOT")
while True:
    now = time.ticks_ms()
    for name, pin in inputs.items():
        reading = pin.value()
        if reading != last[name]:
            last[name] = reading
            changed[name] = now
        elif reading != stable[name] and time.ticks_diff(now, changed[name]) >= 25:
            stable[name] = reading
            if reading == 0:
                if name == "STOP_REQUESTED":
                    led.off()
                emit(name)
    if poller.poll(0):
        char = sys.stdin.read(1)
        if char:
            if char == "\n":
                try:
                    msg = json.loads(buffer)
                    if msg.get("command") == "SET_LED":
                        led.value(1 if msg.get("enabled") is True else 0)
                        emit("LED_ACK")
                except (ValueError, AttributeError):
                    emit("INVALID_COMMAND")
                buffer = ""
            elif len(buffer) < 256:
                buffer += char
            else:
                buffer = ""
    time.sleep_ms(5)
