import pytest

from focus_eval.textnorm import cer, edit_distance, normalize_arabic, wer


def test_normalization_rules():
    assert normalize_arabic("أَنَا إيه؟ آه!") == "انا ايه اه"
    assert normalize_arabic("مدرسة") == "مدرسه"
    assert normalize_arabic("على") == "علي"
    assert normalize_arabic("كــلام") == "كلام"
    assert normalize_arabic("سنة ٣٦") == "سنه 36"
    assert normalize_arabic("  a_b,  c ") == "a b c"


def test_edit_distance_known_values():
    assert edit_distance("kitten", "sitting") == 3
    assert edit_distance("", "abc") == 3
    assert edit_distance("abc", "") == 3
    assert edit_distance(["a", "b"], ["a", "b"]) == 0


def test_wer_known_values():
    assert wer("انا كويس", "انا كويس") == 0.0
    assert wer("انا كويس جدا", "انا كويس") == pytest.approx(1 / 3)
    assert wer("a b", "c d e") == pytest.approx(1.5)


def test_cer_ignores_spaces_and_spelling_variants():
    assert cer("أنا كويس", "انا كويس") == 0.0
    assert cer("انا كويس", "اناكويس") == 0.0
    assert cer("كتاب", "كتب") == pytest.approx(0.25)


def test_empty_reference_is_an_error_not_a_zero():
    with pytest.raises(ValueError):
        cer("؟!", "كلام")
    with pytest.raises(ValueError):
        wer("", "")
