import os
import argparse
from loguru import logger
from utils.config import config
from main.integration import getCalender

VERSION = "1.0.3"

if __name__ == "__main__":
    def formatter(prog):
        return argparse.HelpFormatter(prog, max_help_position=52)

    parser = argparse.ArgumentParser(
        prog="zjuical.py",
        description="A command-line utility for generating \
            class schedule iCalender file from extracting \
            data from ZJU ZDBK API. Refactored based \
            on Python by Xecades. Revised by AyanamiRei.",
        formatter_class=formatter
    )
    parse = parser.add_argument

    parse("-u", "--username", type=str, required=True, help="ZJUAM username")
    parse("-p", "--password", type=str, required=True, help="ZJUAM password")
    parse("-c", "--config", type=str, default="configs/config.json",
          help="config file (default \"configs/config.json\")")
    parse("-o", "--output", type=str, default=None,
          help="output file (default: auto-generated based on student name and term)")
    parse("-f", "--force", action="store_true",
          help="force write to target file")
    parse("--skip-verification", action="store_true",
          help="skip verification for non-undergraduate account")
    
    # 新增参数
    parse("--exams-only", action="store_true", help="only export exams")
    parse("--courses-only", action="store_true", help="only export courses")
    
    parse("-v", "--version", action="version",
          version=f"%(prog)s v{VERSION}", help="version for zjuical")

    args = parser.parse_args()

    logger.info(f"ZJU-ICAL-PY (v{VERSION}) by Xecades, Revised by AyanamiRei")

    if args.exams_only and args.courses_only:
        logger.error("参数 --exams-only 和 --courses-only 不能同时使用")
        exit(1)

    config.load(args.config)
    
    # 获取日历内容和建议的文件名
    cal_content, suggested_filename = getCalender(
        args.username, args.password, args.skip_verification, 
        exams_only=args.exams_only, courses_only=args.courses_only
    )
    
    # 确定最终输出文件名
    # 如果用户指定了 -o，则使用用户指定的
    # 否则使用自动生成的建议文件名
    output_file = args.output if args.output else suggested_filename
    
    if os.path.exists(output_file):
        if not args.force:
            logger.error(f"输出文件 {output_file} 已存在，请使用 -f 参数强制覆盖")
            exit(1)
        else:
            logger.warning(f"输出文件 {output_file} 已存在，将被覆盖")

    with open(output_file, "w", encoding="utf-8") as f:
        logger.info(f"正在写入文件 {output_file}")
        f.write(cal_content)

    logger.success(f"日历文件生成完毕: {output_file}")
