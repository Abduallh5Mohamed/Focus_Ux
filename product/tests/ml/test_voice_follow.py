from focus_ml.voice_follow import (
    CONFLICT, UNCERTAIN, VISUAL, VOICE_FOLLOW, Observation, VoiceFollowConfig,
    VoiceprintEnroller, classify, wrong_person_rate,
)

A = [1.0, 0.0, 0.0]
B = [0.0, 1.0, 0.0]
NEAR_A = [0.9, 0.1, 0.0]
CLOSE_B = [0.7, 0.7, 0.0]  # similar-voice impostor


def obs(s, e, vis, emb=None, lip=0.9, q=0.9):
    return Observation(s, e, vis, emb, lip, q)


def enrolled():
    en = VoiceprintEnroller()
    en.add(obs(0, 4000, True, A))
    return en.voiceprint()


def test_insufficient_voiceprint_not_issued_and_hidden_is_uncertain():
    en = VoiceprintEnroller()
    assert en.add(obs(0, 2000, True, A))
    assert en.voiceprint() is None
    assert not en.add(obs(2000, 6000, True, A, lip=0.1))   # lips still
    assert not en.add(obs(2000, 6000, True, A, q=0.2))     # noisy
    assert not en.add(obs(2000, 6000, False, A))           # face hidden
    assert not en.ready
    p = classify([obs(6000, 8000, False, A)], en.voiceprint())[0]
    assert p.state == UNCERTAIN and p.reason == "no_voiceprint" and not p.output_allowed


def test_face_return_goes_back_to_visual():
    vp = enrolled()
    ps = classify([obs(0, 1, False, NEAR_A), obs(1, 2, True, NEAR_A)], vp)
    assert [p.state for p in ps] == [VOICE_FOLLOW, VISUAL]


def test_conflict_with_visible_face_is_recorded_and_muted():
    p = classify([obs(0, 1000, True, B)], enrolled())[0]
    assert p.state == CONFLICT and not p.output_allowed


def test_uncertainty_threshold():
    cfg = VoiceFollowConfig(follow_threshold=0.9)
    vp = enrolled()
    assert classify([obs(0, 1, False, [0.95, 0.05, 0])], vp, cfg)[0].state == VOICE_FOLLOW
    low = classify([obs(0, 1, False, CLOSE_B)], vp, cfg)[0]
    assert low.state == UNCERTAIN and not low.output_allowed


def test_wrong_person_rate_similar_and_overlapping_voices():
    vp = enrolled()
    seq = [obs(0, 1000, False, NEAR_A), obs(1000, 2000, False, CLOSE_B), obs(2000, 3000, False, B)]
    ps = classify(seq, vp, VoiceFollowConfig(follow_threshold=0.8))  # impostor sim ~0.71
    m = wrong_person_rate(ps, [True, False, False])
    assert m["hidden_periods"] == 3 and m["wrong_periods"] == 0
    # no voice path (no voiceprint, naive pass-through) would be wrong: baseline
    naive = [type(p)(p.start_ms, p.end_ms, VOICE_FOLLOW, "naive", None, True) for p in ps]
    assert wrong_person_rate(naive, [True, False, False])["wrong_periods"] == 2


def test_discard_wipes_voiceprint():
    en = VoiceprintEnroller()
    en.add(obs(0, 4000, True, A))
    en.discard()
    assert en.voiceprint() is None
