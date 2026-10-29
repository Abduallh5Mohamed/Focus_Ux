import os
import sys

_PACKAGE_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "packages", "ml")
sys.path.insert(0, os.path.abspath(_PACKAGE_ROOT))
