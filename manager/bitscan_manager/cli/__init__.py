import argparse
import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bitscan-manager", description="Bitscan manager server CLI."
    )
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["-h"], ["--help"]):
        parser.print_help()
        return 0
    parser.print_usage(sys.stderr)
    print("bitscan-manager: error: no command is implemented yet", file=sys.stderr)
    return 2
