import json
from pathlib import Path
import sys

import pytest
from focus_ml.errors import ProcessingError
from focus_ml.voice.resident_separation import ResidentSeparation


def bridge(tmp_path, mode='ok'):
    script=tmp_path/'fake_separator.py'
    script.write_text('''import json,os,sys
from pathlib import Path
for line in sys.stdin:
    task=json.loads(line)
    out=Path(task['out']); out.mkdir(exist_ok=True)
    a=out/'a.wav'; b=out/'b.wav'
    a.write_bytes(b'a'); b.write_bytes(b'b')
    mode=MODE
    if mode=='exit': sys.exit(2)
    paths=[str(a),str(b)] if mode=='ok' else [str(out.parent/'escaped.wav'),str(b)]
    print('vendor progress noise',flush=True)
    print('FOCUS_SEP_RESULT='+json.dumps({'stems':paths,'pid':os.getpid()}),flush=True)
'''.replace('MODE',repr(mode)))
    src=tmp_path/'mix.wav'; src.write_bytes(b'fixture')
    return ResidentSeparation(sys.executable,script,tmp_path,'fake',10),src


def test_resident_model_process_is_reused_and_closed(tmp_path):
    client,src=bridge(tmp_path)
    try:
        assert len(client.request(src,tmp_path/'first'))==2
        pid=client.last_report['pid']
        assert len(client.request(src,tmp_path/'second'))==2
        assert client.last_report['pid']==pid
        process=client.process
    finally:
        client.close()
    assert process.poll() is not None


@pytest.mark.parametrize('mode',['exit','escaped'])
def test_resident_crash_or_untrusted_output_fails_without_fallback(tmp_path,mode):
    client,src=bridge(tmp_path,mode)
    try:
        with pytest.raises(ProcessingError):
            client.request(src,tmp_path/'out')
        assert client.process is None
    finally:
        client.close()
