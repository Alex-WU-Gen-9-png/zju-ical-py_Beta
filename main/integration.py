from loguru import logger

from exam.exam import ExamTable
from ical.ical import Calender
from utils.config import ClassYearAndTerm, TermConfig, config
from zjuam.grs import GrsZjuam
from zjuam.ugrs import UgrsZjuam


def getCalender(
    username: str,
    password: str,
    skip_verification: bool = False,
    exams_only: bool = False,
    courses_only: bool = False,
    *,
    skip_verification_and_use: str | None = None,
    request_delay: float = 1.5,
    include_todos: bool = False,
) -> tuple[str, str]:
    # 保留原有位置参数和二元返回值；上游新增选项使用关键字参数。
    if exams_only and courses_only:
        raise ValueError("参数 --exams-only 和 --courses-only 不能同时使用")
    if not username:
        raise ValueError("用户名不能为空")
    if skip_verification_and_use not in (None, "ugrs", "grs"):
        raise ValueError("登录方式必须是 ugrs 或 grs")

    login_method = skip_verification_and_use
    if login_method is None:
        if username.startswith("3"):
            login_method = "ugrs"
        elif username.startswith(("1", "2")):
            login_method = "grs"
        elif skip_verification:
            logger.warning("跳过学号验证，默认使用本科生途径登录")
            login_method = "ugrs"
        else:
            raise NotImplementedError(
                "不支持的用户类型，请通过 --skip-verification-and-use ugrs/grs 指定登录方式"
            )

    client_type = UgrsZjuam if login_method == "ugrs" else GrsZjuam
    zjuam = client_type(username, password, request_delay)
    zjuam.login()

    termConfigs = config.termConfigs

    def firstMatchTerm(item: ClassYearAndTerm) -> None | TermConfig:
        for tc in termConfigs:
            if tc.Year == item.Year and tc.Term == item.Term:
                return tc
        return None

    cal = Calender()

    # 根据参数决定是否获取考试信息
    exams = ExamTable()
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
        if not courses_only:
            examEvents = exams.toEvents(courses)
            cal.addEvents(examEvents)

    if include_todos:
        todos = zjuam.getTodos()
        cal.addEvents(todos.toEvents(exams))

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
    safe_cal_name = (
        cal_name.replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace("*", "_")
        .replace("?", "_")
        .replace('"', "_")
        .replace("<", "_")
        .replace(">", "_")
        .replace("|", "_")
    )

    suggested_filename = safe_cal_name + ".ics"

    return cal.getICS(icalName=cal_name), suggested_filename
