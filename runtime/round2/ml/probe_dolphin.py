"""Probe: offline Dolphin.from_pretrained via focus_ml-style activation."""
import os, sys, time

os.environ.setdefault("TORCH_HOME", "A:/focus/cache/torch")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HOME", "A:/focus/cache/hf")

sys.path.insert(0, "A:/Focus_Ux/product/packages/ml")
sys.path.insert(0, "A:/focus/Dolphin")
os.chdir("A:/focus/Dolphin")

import torch
t0 = time.perf_counter()
from look2hear.models import Dolphin
m = Dolphin.from_pretrained(
    "JusperLee/Dolphin",
    cache_dir="A:/focus/cache/hf/hub",
    local_files_only=True,
)
t1 = time.perf_counter()
m = m.to("cuda").eval()
print("LOAD_OK cpu_s=%.2f total_s=%.2f" % (t1 - t0, time.perf_counter() - t0))
with torch.inference_mode():
    out = m(torch.zeros(1, 32000, device="cuda"), torch.zeros(1, 1, 50, 88, 88, device="cuda"))
torch.cuda.synchronize()
print("FWD_OK", tuple(out.shape))
