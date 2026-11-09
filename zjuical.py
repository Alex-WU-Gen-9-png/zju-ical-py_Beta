import argparse
import math
import os

from loguru import logger

from main.integration import getCalender
from utils.config import config

VERSION = "1.1.0"


def nonnegative_delay(value: str) -> float:
    delay = float(value)
    if not math.isfinite(delay) or delay < 0:
        raise argparse.ArgumentTypeError("请求间隔必须是有限的非负数")
    return delay


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    def formatter(prog):
        return argparse.HelpFormatter(prog, max_help_position=52)

    parser = argparse.ArgumentParser(
        prog="zjuical.py",
        description="A command-line utility for generating "
        "class schedule iCalender file from extracting "
        "data from ZJU ZDBK API. Refactored based "
        "on Python by Xecades. Revised by AyanamiRei.",
        formatter_class=formatter,
    )
    parse = parser.add_argument
    parse("-u", "--username", type=str, required=True, help="ZJUAM username")
    parse("-p", "--password", type=str, required=True, help="ZJUAM password")
    parse(
        "-c",
        "--config",
        type=str,
        default="configs/config.json",
        help='config file (default "configs/config.json")',
    )
    parse(
        "-a",
        "--all",
        action="store_true",
        help="generate calendar for all config.*.json files in configs folder (overrides --config)",
    )
    parse(
        "-o",
        "--output",
        type=str,
        default=None,
        help="output file (default: auto-generated based on student name and term)",
    )
    parse("-f", "--force", action="store_true", help="force write to target file")
    login = parser.add_mutually_exclusive_group()
    login.add_argument(
        "--skip-verification",
        action="store_true",
        help="legacy option: skip student id verification (unknown ids use undergraduate login)",
    )
    login.add_argument(
        "--skip-verification-and-use",
        choices=["grs", "ugrs"],
        help="skip student id verification and use the specified login method",
    )
    export = parser.add_mutually_exclusive_group()
    export.add_argument("--exams-only", action="store_true", help="only export exams")
    export.add_argument("--courses-only", action="store_true", help="only export courses")
    parse(
        "--delay",
        type=nonnegative_delay,
        default=1.5,
        help="delay between requests in seconds (default 1.5)",
    )
    parse(
        "--include-todos",
        action="store_true",
        help="also include todos (homework deadlines) in the calendar",
    )
    parse(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s v{VERSION}",
        help="version for zjuical",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logger.info(f"ZJU-ICAL-PY (v{VERSION}) by Xecades, Revised by AyanamiRei")

    if args.all:
        config.loadAll()
    else:
        config.load(args.config)

    cal_content, suggested_filename = getCalender(
        args.username,
        args.password,
        args.skip_verification,
        exams_only=args.exams_only,
        courses_only=args.courses_only,
        skip_verification_and_use=args.skip_verification_and_use,
        request_delay=args.delay,
        include_todos=args.include_todos,
    )
    output_file = args.output if args.output else suggested_filename
    if os.path.exists(output_file):
        if not args.force:
            logger.error(f"输出文件 {output_file} 已存在，请使用 -f 参数强制覆盖")
            raise SystemExit(1)
        logger.warning(f"输出文件 {output_file} 已存在，将被覆盖")

    with open(output_file, "w", encoding="utf-8") as f:
        logger.info(f"正在写入文件 {output_file}")
        f.write(cal_content)
    logger.success(f"日历文件生成完毕: {output_file}")


if __name__ == "__main__":
    main()
