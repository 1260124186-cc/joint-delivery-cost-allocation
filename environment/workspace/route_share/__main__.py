import json
import os
import sys
import tempfile
from pathlib import Path

from .engine import coalitions_payload, run_all, shapley_payload
from .settlement import settle_shares


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main() -> int:
    arguments = sys.argv[1:]
    if not arguments:
        print(
            "usage: python -m route_share {coalitions|shapley|settle|run} ...",
            file=sys.stderr,
        )
        return 2

    stage = arguments[0]
    try:
        if stage == "shapley" and len(arguments) == 4:
            instance = _read_json(Path(arguments[1]))
            coalition_file = _read_json(Path(arguments[2]))
            output = Path(arguments[3])
            payload = shapley_payload(instance, coalition_file)
        elif stage == "coalitions" and len(arguments) == 3:
            instance = _read_json(Path(arguments[1]))
            output = Path(arguments[2])
            payload = coalitions_payload(instance)
        elif stage == "settle" and len(arguments) == 4:
            instance = _read_json(Path(arguments[1]))
            shares = _read_json(Path(arguments[2]))
            output = Path(arguments[3])
            payload = settle_shares(instance, shares)
        elif stage == "run" and len(arguments) == 3:
            instance = _read_json(Path(arguments[1]))
            output = Path(arguments[2])
            payload = run_all(instance)
        else:
            print(
                "usage: python -m route_share {coalitions|shapley|settle|run} ...",
                file=sys.stderr,
            )
            return 2
        _write_json(output, payload)
    except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError) as exc:
        print(f"calculation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
