"""Host serial observer only; does NOT control the real audio pipeline.
Requires pyserial in a separate bring-up environment. No ports opened at import.
Usage: python observe_controls.py COM5
"""
import argparse,json,time
def main():
    import serial
    p=argparse.ArgumentParser();p.add_argument("port");args=p.parse_args()
    with serial.Serial(args.port,115200,timeout=1) as conn:
        print("OBSERVER ONLY: stop/select are logged, not executed by FOCUS.")
        while True:
            raw=conn.readline()
            if not raw:continue
            try:
                msg=json.loads(raw)
                if msg.get("protocol")=="focus-controls-v1":
                    print(json.dumps({"received_monotonic_s":time.monotonic(),"device":msg}))
            except (ValueError,UnicodeDecodeError):
                print("Ignored non-protocol serial output")
if __name__=="__main__":main()
