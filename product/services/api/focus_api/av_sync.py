"""Optional active-speaker evidence. This module never renders/extracts audio."""
import json
import os
from pathlib import Path
import subprocess
import tempfile


def score_face(video, audio, face, temp_root):
    python = os.environ.get('FOCUS_TALKNET_PYTHON')
    if not python:
        raise RuntimeError('TalkNet is not configured')
    script = Path(__file__).resolve().parents[3] / 'tools' / 'talknet_score.py'
    with tempfile.TemporaryDirectory(dir=temp_root, prefix='av-sync-') as tmp:
        request, output = Path(tmp)/'request.json', Path(tmp)/'scores.json'
        request.write_text(json.dumps({'video':str(video),'audio':str(audio),
            'bbox':list(face.bbox),'frame_size':list(face.frame_size),'timestamp_ms':face.timestamp_ms}))
        result = subprocess.run([python,'-B',str(script),str(request),str(output)],
                                capture_output=True,text=True,timeout=240)
        if result.returncode:
            # Avoid reflecting local paths or arbitrary subprocess output to clients.
            import logging
            logging.getLogger(__name__).warning('TalkNet scoring failed: %s',result.stderr[-3000:])
            raise RuntimeError('TalkNet face/audio scoring failed on the inference computer')
        data=json.loads(output.read_text())
        if data.get('kind')!='av_sync_v1' or not isinstance(data.get('windows'),list):
            raise RuntimeError('Invalid active-speaker evidence')
        return data
