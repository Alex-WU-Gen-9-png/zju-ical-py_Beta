# Undergraduate Students
import re
import json
import time
from zjuam.base import Zjuam
from course.ugrs_course import UGRSCourseTable
from exam.exam import ExamTable
from utils.const import Term
from loguru import logger
from course.convert import ugrsClassTermToQueryString


class UgrsZjuam(Zjuam):
    COURSE_URL = "https://zdbk.zju.edu.cn/jwglxt/kbcx/xskbcx_cxXsKb.html"
    EXAM_URL = "https://zdbk.zju.edu.cn/jwglxt/xskscx/kscx_cxXsgrksIndex.html?doType=query&gnmkdm=N509070&su=%s"  # gnmkdm=功能模块代码
    ZDBK_LOGIN_URL = "https://zjuam.zju.edu.cn/cas/login?service=https%3A%2F%2Fzdbk.zju.edu.cn%2Fjwglxt%2Fxtgl%2Flogin_ssologin.html"

    def __init__(self, username: str, password: str):
        super().__init__(username, password)

    def login(self) -> None:
        logger.info("开始通过 ZJUAM 本科生途径登录")

        # stage 1: get csrf key
        try:
            res = self.r.get(self.ZDBK_LOGIN_URL)
            assert res.status_code == 200, "状态码错误"
            regex = r"\"execution\" value=\"(.*?)\" \/>"
            csrf = re.search(regex, res.text).group(1)
            assert csrf, "CSRF Key 为空"
        except Exception as e:
            logger.error(f"CSRF Key 获取失败: {e}")
            raise e
        logger.success("CSRF Key 获取成功")

        # stage 2: get pub key
        try:
            res = self.r.get(self.PUBKEY_URL)
            pubkey = res.json()
            N, E = pubkey["modulus"], pubkey["exponent"]
            N, E = int(N, 16), int(E, 16)
            plain = int.from_bytes(self.password.encode(), "big")
            cipher = hex(pow(plain, E, N))[2:]
            cipher = "0" * (128 - len(cipher)) + cipher
        except Exception as e:
            logger.error(f"RSA 公钥获取失败: {e}")
            raise e
        logger.success("RSA 公钥获取成功")

        # stage 3: fire target
        try:
            res = self.r.post(self.LOGIN_URL, data={
                "username": self.username,
                "password": cipher,
                "authcode":  "",
                "execution": csrf,
                "_eventId":  "submit",
            })
            assert "用户名或密码错误" not in res.text, "用户名或密码错误，请确保用户名密码正确后再运行程序，否则有账号被锁定的风险"
            assert "账号被锁定" not in res.text, "输错密码次数太多，账号被锁定，请过段时间再使用"
            
            logger.info(f"登录请求结束，当前 URL: {res.url}")

        except Exception as e:
            logger.error(f"ZJUAM 登录失败: {e}")
            raise e
        logger.success("ZJUAM 登录成功")

    def getCourses(self, year: str, term: Term, exams: ExamTable) -> UGRSCourseTable:
        logger.info(f"开始获取[{year}-{term.value}]课程信息")
        res = None
        try:
            termQuery = ugrsClassTermToQueryString(term)
            assert termQuery, "学期参数错误"
            
            # 增加延时，避免请求过快导致 Session 异常或被封禁
            time.sleep(1)
            
            res = self.r.post(self.COURSE_URL, data={
                "xnm": year,
                "xqm": termQuery,
            })
            
            # 检查是否返回了 HTML 错误页面
            if res.text.strip().startswith("<!doctype html>") or "<title>错误提示</title>" in res.text:
                 logger.warning("检测到 HTML 错误页面")
                 logger.debug(f"Response URL: {res.url}")
                 raise Exception("Session 可能已过期或未正确建立，服务器返回了 HTML 错误页面")

            content = res.json()
            
            if isinstance(content, str):
                if "captcha" in content or "验证码" in content:
                    raise Exception(f"服务器返回验证码错误: {content}")
                try:
                    content = json.loads(content)
                except Exception as e:
                    logger.error(f"JSON 二次解析失败: {e}")
                    raise Exception(f"服务器返回了无法解析的字符串: {content}")

            if not isinstance(content, dict):
                raise Exception(f"返回内容格式错误: 期望 dict, 实际 {type(content)}")

            # 提取用户信息
            if not self.student_info:
                self.student_info = {
                    "xm": content.get("xm", ""),
                    "xh": content.get("xh", ""),
                    "xy": content.get("xy", ""),
                    "zy": content.get("zy", ""),
                    "xzb": content.get("xzb", "")
                }
                logger.info(f"获取到用户信息: {self.student_info['xm']} ({self.student_info['xh']}) - {self.student_info['xy']}")

            kblist = content.get("kbList")
            if kblist is None:
                logger.error("返回 JSON 中未找到 kbList 字段")
                raise Exception("数据格式错误：缺少 kbList")

            ct = UGRSCourseTable()
            ct.fromRes(kblist)
            ct.merge()
            ct.communicate(exams)
        except json.JSONDecodeError as e:
            logger.error(f"课程信息获取失败 (JSON 解析错误): {e}")
            if res is not None:
                logger.debug(f"返回内容: {res.text[:500]}")
            raise e
        except Exception as e:
            logger.error(f"课程信息获取失败: {e}")
            raise e
        logger.success(f"[{year}-{term.value}]课程信息获取成功")
        return ct

    def getExams(self, count: int = 5000) -> ExamTable:
        logger.info("开始获取考试信息")
        res = None
        try:
            # 增加延时
            time.sleep(1)
            
            res = self.r.post(self.EXAM_URL % self.username, data={
                "_search": "false",
                "nd": str(int(time.time() * 1000)),
                "queryModel.showCount": str(count),
                "queryModel.currentPage": "1",
                "queryModel.sortName": "xkkh",
                "queryModel.sortOrder": "asc",
                "time": "0",
            })
            content = res.json()
            items = content["items"]
            et = ExamTable()
            et.fromZdbk(items)
        except json.JSONDecodeError as e:
            logger.error(f"考试信息获取失败: {e}")
            if res is not None:
                logger.info(f"返回内容: {res.text}")
            raise e
        except Exception as e:
            logger.error(f"考试信息获取失败: {e}")
            raise e
        logger.success("考试信息获取成功")
        return et
