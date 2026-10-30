"""Check an Egyptian voice recording set: python validate_voice_recordings.py <dir>
Exit 1 when blocking errors exist; coverage gaps are printed as warnings."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "product" / "packages" / "eval"))
from focus_eval.voice_dataset import VoiceDatasetError, validate  # noqa: E402


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print(__doc__)
        return 2
    try:
        rep = validate(args[0])
    except VoiceDatasetError as exc:
        print("error:", exc, file=sys.stderr)
        return 2
    for e in rep["errors"]:
        print("ERROR  ", e)
    for w in rep["warnings"]:
        print("WARNING", w)
    print(json.dumps(rep["coverage"], indent=1))
    print(f"{len(rep['errors'])} error(s), {len(rep['warnings'])} coverage warning(s)")
    return 1 if rep["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
