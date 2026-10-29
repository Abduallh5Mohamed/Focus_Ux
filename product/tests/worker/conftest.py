"""Path bootstrap so tests run with any Python interpreter without install steps."""
import os
import sys

PRODUCT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for candidate in (PRODUCT_ROOT,):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
