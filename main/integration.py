from ical.ical import Calender
from loguru import logger
from utils.config import config, ClassYearAndTerm, TermConfig
from zjuam.ugrs import UgrsZjuam
from zjuam.grs import GrsZjuam


def getCalender(username: str, password: str, skip_verification: bool, 
                exams_only: bool = False, courses_only: bool = False) -> tuple[str, str]:
    match username[0]:
        case "3":
            logger.info("检测到本科生学号，使用本科生途径登录")
            zjuam = UgrsZjuam(username, password)
        case "1" | "2":
            logger.info("检测到研究生学号，使用研究生途径登录")
            zjuam = GrsZjuam(username, password)
        case _:
            if skip_verification:
                logger.warning("跳过学号验证")
            else:
                logger.error("学号不以 1/2/3 开头，不确保本项目能在除本科生/研究生之外的账号使用")
                logger.info(
                    "你可以通过 --skip-verification 参数跳过此检查，同时欢迎向作者反馈其他类型账号使用情况")
                raise NotImplementedError("不支持的用户类型")
        
    zjuam.login()

    termConfigs = config.termConfigs

    def firstMatchTerm(item: ClassYearAndTerm) -> None | TermConfig:
        for tc in termConfigs:
            if tc.Year == item.Year and tc.Term == item.Term:
                return tc
        return None

    cal = Calender()
    
    # 根据参数决定是否获取考试信息
    exams = None
    if not courses_only:
        exams = zjuam.getExams()

    for item in config.classTerms:
        tc = firstMatchTerm(item)
        if tc is None:
            logger.error(f"配置文件错误，未找到 {item.Year}-{item.Term.value} 的学期配置")
            exit(1)

        courses = zjuam.getCourses(item.Year, item.Term, exams)
        
        # 根据参数决定是否添加课程事件
        if not exams_only:
            courseEvents = courses.toEvents(termConfig=tc)
            cal.addEvents(courseEvents)
            
        # 根据参数决定是否添加考试事件
        if not courses_only and exams is not None:
            examEvents = exams.toEvents(courses)
            cal.addEvents(examEvents)

    # 动态生成日历名称和建议文件名
    # 优先使用提取到的用户信息
    info = zjuam.student_info
    base_name = config.toTermString()
    
    # 目标格式: 学院_专业_行政班_姓名_学号_学期+后缀
    parts = []
    if info:
        # 按顺序添加存在的字段
        for key in ["xy", "zy", "xzb", "xm", "xh"]:
            val = info.get(key)
            if val:
                parts.append(val)
    
    suffix = ""
    if exams_only:
        suffix = "考试安排"
    elif courses_only:
        suffix = "课程表"
    else:
        suffix = "课程与考试表"
        
    if parts:
        # 使用下划线连接各部分
        prefix = "_".join(parts)
        cal_name = f"{prefix}_{base_name}{suffix}"
    else:
        cal_name = f"{base_name}{suffix}"

    # 移除文件名中可能不合法的字符
    safe_cal_name = cal_name.replace("/", "_").replace("\\", "_").replace(":", "_").replace("*", "_").replace("?", "_").replace("\"", "_").replace("<", "_").replace(">", "_").replace("|", "_")
    
    suggested_filename = safe_cal_name + ".ics"

    return cal.getICS(icalName=cal_name), suggested_filename
