import os
import sys

_T = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_P = os.path.join(_T, "..", "packages")
for p in (os.path.join(_P, "ml"), os.path.join(_P, "eval"), os.path.join(_T, "voice")):
    sys.path.insert(0, os.path.abspath(p))
