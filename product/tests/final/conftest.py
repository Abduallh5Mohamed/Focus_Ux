import os
import sys

_P = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for sub in ("tests/voice", "tools", "packages/eval", "packages/ml"):
    path = os.path.join(_P, sub)
    if path not in sys.path:
        sys.path.insert(0, path)
