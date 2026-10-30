"""Real local GPU smoke on caller-provided media; never uses test doubles."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / 'product' / 'packages' / 'ml'))
    from focus_ml.config import AdapterConfig
    from focus_ml.normalize import normalize_input
    from focus_ml.runtime import LocalEngine, offline_inference

    args.output.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed', 'fake_backend': False, 'source': str(args.video.resolve())}
    started = time.perf_counter()
    try:
        import numpy as np
        import soundfile as sf
        import torch

        report.update(torch=torch.__version__, cuda=torch.version.cuda)
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA is unavailable')
        report['gpu'] = torch.cuda.get_device_name(0)
        config = AdapterConfig.from_env()
        engine = LocalEngine(config)
        engine.initialize()
        report['load_s'] = time.perf_counter() - started
        # Upstream now includes training/reconstruction heads omitted by this
        # released inference checkpoint. Fail on any missing inference parameter,
        # and guard omitted heads against execution throughout the real smoke.
        from safetensors.torch import load_file
        snapshots = Path(config.model_cache) / 'hub' / 'models--JusperLee--Dolphin'
        revision = (snapshots / 'refs' / 'main').read_text().strip()
        checkpoint = load_file(str(snapshots / 'snapshots' / revision / 'model.safetensors'))
        model = engine.models.dolphin
        with offline_inference():
            incompatible = model.load_state_dict(checkpoint, strict=False)
        unused_prefixes = (
            'video_encoder.semantic_model.distill_out.',
            'video_encoder.recon_model.conv_out.',
            'video_encoder.recon_model.decoder_layers.',
        )
        missing_inference = [key for key in incompatible.missing_keys if not key.startswith(unused_prefixes)]
        if incompatible.unexpected_keys or missing_inference:
            raise RuntimeError(f'Inference checkpoint mismatch: {missing_inference}, {incompatible.unexpected_keys}')
        if model.training:
            raise RuntimeError('Model must be in eval mode')
        guarded = set()
        for key in incompatible.missing_keys:
            module_path = key.rsplit('.', 1)[0]
            if module_path not in guarded:
                def reject_uninitialized(_module, _inputs, name=module_path):
                    raise RuntimeError('Uninitialized training head was executed: ' + name)
                model.get_submodule(module_path).register_forward_pre_hook(reject_uninitialized)
                guarded.add(module_path)
        report['all_inference_parameters_loaded'] = True
        report['omitted_unused_training_keys'] = incompatible.missing_keys
        report['model_revision'] = revision
        normalized = normalize_input(str(args.video.resolve()), str(args.output / 'normalized'), config)
        video_id = 'local-gpu-smoke-' + hashlib.sha256(args.video.read_bytes()).hexdigest()[:24]
        faces = engine.detect(video_id, normalized.video_path)
        repeated = engine.detect(video_id, normalized.video_path)
        if not faces or faces != repeated:
            raise RuntimeError('No faces or unstable repeated face candidates')
        from focus_ml.identity import make_face_id

        report['faces'] = []
        for index, face in enumerate(faces[:2]):
            face_id = make_face_id(video_id, face['timestamp_ms'], tuple(face['bbox']), tuple(face['frame_size']))
            job_dir = args.output / f'target-{index}'
            job_dir.mkdir(exist_ok=True)
            before = time.perf_counter()
            result = engine.extract(video_id, normalized.video_path, face_id, str(job_dir))
            audio, rate = sf.read(result.wav_path)
            if rate != 16000 or audio.ndim != 1 or not np.isfinite(audio).all() or not np.any(audio):
                raise RuntimeError('Invalid or silent real extraction output')
            duration_ms = round(len(audio) * 1000 / rate)
            if result.source_offset_ms != 0 or abs(duration_ms - normalized.duration_ms) > 80:
                raise RuntimeError('Output does not preserve the canonical timeline')
            record = {
                'face_id': face_id, 'bbox': face['bbox'], 'wav_path': result.wav_path,
                'duration_ms': duration_ms, 'elapsed_s': time.perf_counter() - before,
                'sha256': hashlib.sha256(Path(result.wav_path).read_bytes()).hexdigest(),
                'rms': float(np.sqrt(np.mean(audio ** 2))), 'timings': result.timings,
            }
            report['faces'].append(record)
            print('REAL_TARGET_COMPLETE', face_id, duration_ms, flush=True)
        if len(report['faces']) == 2 and report['faces'][0]['sha256'] == report['faces'][1]['sha256']:
            raise RuntimeError('Different target selections produced identical audio')
        report['status'] = 'passed'
        report['identity_quality'] = 'No listening evaluation or reference-audio quality score claimed.'
    except Exception as exc:
        report['error'] = {
            'type': type(exc).__name__, 'message': str(exc), 'detail': getattr(exc, 'detail', ''),
        }
        print(json.dumps(report['error']), flush=True)
    report['total_s'] = time.perf_counter() - started
    (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('GPU_SMOKE', report['status'], flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
