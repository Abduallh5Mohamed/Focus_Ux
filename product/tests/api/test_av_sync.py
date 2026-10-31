"""Selection semantics with synthetic scores, not model-accuracy evidence."""
from services.api.focus_api.voice_suggest import rank_voices


def analysis(overlap=False, usable=(True, True)):
    return {'speakers':[{'speaker':s,'usable':u} for s,u in zip(('A','B'),usable)],
            'diarization':{'turns':[{'start':0,'end':3,'speaker':'A'},
                                      {'start':3,'end':6,'speaker':'B'}],
                           'overlaps':[{'start':0,'end':6}] if overlap else []}}


def evidence(a=2,b=-2):
    return {'kind':'av_sync_v1','windows':[{'start_ms':i*100,'end_ms':(i+1)*100,
                'score':a if i<30 else b} for i in range(60)]}


def test_sync_ranks_the_matching_speaker_not_the_first_voice():
    r=rank_voices(analysis(),evidence(-2,2))
    assert r['evidence']=='av_sync'
    assert [x['index'] for x in r['candidates'] if x['suggested']]==[1]


def test_sync_abstains_when_all_speech_overlaps():
    assert not any(x['suggested'] for x in rank_voices(analysis(True),evidence())['candidates'])


def test_sync_abstains_without_competing_usable_fingerprint():
    assert not any(x['suggested'] for x in rank_voices(analysis(usable=(True,False)),evidence())['candidates'])


def test_sync_abstains_when_every_face_appears_to_speak():
    assert not any(x['suggested'] for x in rank_voices(analysis(),evidence(2,2))['candidates'])


def test_sync_rejects_nonfinite_scores_as_evidence():
    assert not any(x['suggested'] for x in rank_voices(analysis(),evidence(float('nan'),float('inf')))['candidates'])
