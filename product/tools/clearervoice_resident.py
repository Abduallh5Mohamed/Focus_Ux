"""Private stdio separation process. Keeps one offline CUDA model resident.

No network listener, tokens or uploads. Parent supplies local temporary paths.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import time

PREFIX = 'FOCUS_SEP_RESULT='

def emit(value):
    print(PREFIX + json.dumps(value), flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--home', required=True)
    ap.add_argument('--model', required=True)
    args = ap.parse_args()
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    import torch
    if not torch.cuda.is_available():
        emit({'error': 'CUDA is unavailable; resident separation will not silently fall back to CPU'})
        return 3
    # Deny incidental vendor downloads even when an asset is incomplete.
    def denied(*a, **k):
        raise RuntimeError('Network access is disabled in resident separation')
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    os.chdir(args.home)
    from clearvoice import ClearVoice
    started = time.perf_counter()
    model = ClearVoice(task='speech_separation', model_names=[args.model])
    if any(str(m.device) != 'cuda' for m in model.models):
        emit({'error': 'Vendor model selected a non-CUDA device; refusing CPU fallback'})
        return 3
    torch.cuda.synchronize()
    load_s = time.perf_counter() - started
    for line in sys.stdin:
        try:
            request = json.loads(line)
            src = Path(request['src']).resolve()
            out = Path(request['out']).resolve()
            if not src.is_file() or out.parent != src.parent:
                raise ValueError('Invalid local task directory')
            out.mkdir(exist_ok=True)
            torch.cuda.synchronize()
            started = time.perf_counter()
            model(input_path=str(src), online_write=True, output_path=str(out))
            torch.cuda.synchronize()
            files = [str(p.resolve()) for p in sorted(out.rglob('*.wav'))]
            if len(files) != 2:
                raise RuntimeError('Expected exactly two separated sources')
            emit({'stems': files, 'load_seconds': load_s,
                  'inference_seconds': time.perf_counter() - started, 'device': 'cuda'})
        except Exception as exc:
            emit({'error': type(exc).__name__ + ': ' + str(exc)[:500]})
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        emit({'error': type(exc).__name__ + ': ' + str(exc)[:500]})
        raise SystemExit(3)
