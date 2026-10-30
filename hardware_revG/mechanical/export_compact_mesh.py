import sys
from pathlib import Path

sys.argv = [sys.argv[0], 'compact']
exec(compile(Path(__file__).with_name('export_review_mesh.py').read_text(), 'export_review_mesh.py', 'exec'))
