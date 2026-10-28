"""JSON-file interface for the local control plane and portable evidence bundles."""

import argparse
import sys

from .api import get_case, prepare_case
from .common import ScienceError, atomic_result, read_json


def main(argv=None):
    parser = argparse.ArgumentParser(description="Crucible trusted authored science adapter")
    parser.add_argument("stage", choices=["metadata", "prepare", "reproduce", "explore", "predict", "verify", "export", "reverify", "rerun"])
    parser.add_argument("--adapter", choices=["occupancy", "synthetic"])
    parser.add_argument("--root")
    parser.add_argument("--source-zip")
    parser.add_argument("--input")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.stage == "metadata":
            if not args.adapter:
                raise ScienceError("ADAPTER_REQUIRED", "metadata requires --adapter")
            result = get_case(args.adapter)
        elif args.stage == "prepare":
            if not args.adapter or not args.root:
                raise ScienceError("PREPARATION_INPUT", "prepare requires --adapter and --root")
            result = prepare_case(args.adapter, args.root, source_zip=args.source_zip)
        else:
            if not args.input:
                raise ScienceError("REQUEST_REQUIRED", "Numerical stages require --input REQUEST.json")
            request = read_json(args.input)
            if args.stage == "export":
                from .bundle import export_case
                result = export_case(request)
            else:
                from . import orchestrate
                result = getattr(orchestrate, args.stage)(request)
        atomic_result(args.output, result)
        return 0
    except ScienceError as exc:
        atomic_result(args.output, exc.as_dict())
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 2
    except (KeyError, TypeError, ValueError, OSError) as exc:
        error = ScienceError("INVALID_STAGE_INPUT", f"Trusted stage could not complete ({type(exc).__name__}); inspect its saved inputs and receipts", True)
        atomic_result(args.output, error.as_dict())
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
