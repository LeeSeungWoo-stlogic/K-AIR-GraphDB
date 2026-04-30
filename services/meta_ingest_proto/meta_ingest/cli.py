from __future__ import annotations

import argparse

from . import _paths  # noqa: F401 — libs on sys.path

from .pipeline import cmd_extract, cmd_load, cmd_run_all


def main() -> None:
    ap = argparse.ArgumentParser(
        description="DB catalog extract → GraphDB t2s_* (+ optional AGE physical graph)"
    )
    sub = ap.add_subparsers(dest="cmd")

    p_ext = sub.add_parser("extract", help="원천 DB만 읽어 catalog JSON 저장")
    p_ext.add_argument("-o", "--output", required=True, help="출력 JSON 경로")

    p_ld = sub.add_parser("load", help="catalog JSON → TARGET t2s_* (+ AGE 기본)")
    p_ld.add_argument("-i", "--input", required=True, help="입력 JSON 경로")

    sub.add_parser("run", help="extract+load 한 번에 (기본과 동일)")

    args = ap.parse_args()
    if args.cmd == "extract":
        cmd_extract(args.output)
    elif args.cmd == "load":
        cmd_load(args.input)
    elif args.cmd == "run":
        cmd_run_all()
    else:
        cmd_run_all()
