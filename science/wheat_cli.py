"""JSON-file CLI for the isolated wheat adapter; metadata imports no torch."""

import argparse
import sys

from . import wheat
from .common import ScienceError, atomic_result, read_json


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["metadata", "prepare", "train", "explore", "predict", "verify", "export", "rerun", "reverify", "oracle"])
    parser.add_argument("--input")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.stage == "metadata":
            result = wheat.metadata()
        else:
            if not args.input:
                raise ScienceError("REQUEST_REQUIRED", "Wheat numerical stages require --input REQUEST.json")
            request = read_json(args.input)
            function = wheat.export_case if args.stage == "export" else getattr(wheat, args.stage)
            result = function(request)
        atomic_result(args.output, result)
        return 0
    except ScienceError as exc:
        atomic_result(args.output, exc.as_dict())
        print(exc.code + ": " + exc.message, file=sys.stderr)
        return 2
    except (KeyError, ValueError, TypeError, OSError) as exc:
        error = ScienceError("INVALID_STAGE_INPUT", "Wheat stage could not complete (" + type(exc).__name__ + "); inspect saved inputs and receipts", True)
        atomic_result(args.output, error.as_dict())
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
