"""离线验证本地定制功能与上游新增功能的组合行为。"""

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from loguru import logger

import webical
import zjuical
from course.ugrs_course import UGRSCourse, UGRSCourseTable
from exam.exam import ExamTable
from main.integration import getCalender
from todos.todos import TodoTable
from utils.config import Config, config
from utils.const import Term
from zjuam.grs import GrsZjuam
from zjuam.ugrs import UgrsZjuam

logger.remove()
ROOT = Path(__file__).resolve().parents[1]
STUDENT = {
    "xy": "测试学院",
    "zy": "测试专业",
    "xzb": "测试班",
    "xm": "测试姓名",
    "xh": "3000000000",
}
CLASS_ID = "(2026-2027-1)-000000001-1"


def raw_course(**overrides):
    return {
        "xkkh": CLASS_ID,
        "xqj": "1",
        "dsz": "2",
        "xxq": "秋冬春夏",
        "kcb": "测试课程<br>1-8周<br>测试教师<br>东1-101",
        "djj": "1",
        "skcd": "2",
        **overrides,
    }


def raw_exam():
    return {
        "xkkh": CLASS_ID,
        "kcmc": "测试课程",
        "xf": "2.0",
        "kssj": "2027年01月05日(08:00-10:00)",
        "jsmc": "东2-201",
        "zwxh": "09",
    }


def raw_todo(**overrides):
    return {
        "is_student": True,
        "course_name": "测试课程",
        "course_code": CLASS_ID,
        "title": "测试作业",
        "end_time": "2026-11-10T08:00:00Z",
        **overrides,
    }


def response(content, *, text=None):
    return Mock(text=json.dumps(content) if text is None else text, json=Mock(return_value=content))


class OfflineTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch(
            "requests.sessions.Session.request", side_effect=AssertionError("测试禁止联网")
        ).start()


class IntegrationTests(OfflineTest):
    def setUp(self):
        super().setUp()
        config.load(str(ROOT / "configs/config.json"))
        self.client = UgrsZjuam("3000000000", "offline", 0)
        self.client.login = Mock()
        self.client.r = Mock()

        def post(url, **kwargs):
            if url.startswith(self.client.EXAM_URL.split("%s")[0]):
                return response({"items": [raw_exam()]})
            self.assertEqual(url, self.client.COURSE_URL)
            return response({**STUDENT, "kbList": [raw_course()]})

        self.client.r.post.side_effect = post
        self.client.r.get.return_value = response({"todo_list": [raw_todo()]})
        self.factory = patch("main.integration.UgrsZjuam", return_value=self.client).start()
        patch("time.sleep").start()

    def generate(self, **kwargs):
        return getCalender("3000000000", "offline", False, request_delay=0, **kwargs)

    def test_default_includes_courses_and_exactly_one_exam(self):
        ics, filename = self.generate()
        self.assertIn("SUMMARY;LANGUAGE=zh-cn:测试课程\r\n", ics)
        self.assertEqual(ics.count("[务必核对!]测试课程 期末考试"), 1)
        self.assertIn("LOCATION:东2-201 (座位号: 09)", ics)
        self.assertIn("学分: 2.0", ics)
        self.assertEqual(
            filename, "测试学院_测试专业_测试班_测试姓名_3000000000_2026-2027 秋冬课程与考试表.ics"
        )
        self.assertIn("X-WR-CALNAME:" + filename[:-4], ics)
        self.assertTrue(ics.endswith("END:VCALENDAR\r\n"))

    def test_exams_only_does_not_generate_course_events(self):
        ics, filename = self.generate(exams_only=True)
        self.assertEqual(ics.count("BEGIN:VEVENT"), 1)
        self.assertNotIn("SUMMARY;LANGUAGE=zh-cn:测试课程\r\n", ics)
        self.assertTrue(filename.endswith("考试安排.ics"))

    def test_courses_only_skips_exam_request(self):
        ics, filename = self.generate(courses_only=True)
        self.assertIn("SUMMARY;LANGUAGE=zh-cn:测试课程\r\n", ics)
        self.assertNotIn("务必核对", ics)
        self.assertTrue(filename.endswith("课程表.ics"))
        self.assertTrue(
            all(
                call.args[0] == self.client.COURSE_URL for call in self.client.r.post.call_args_list
            )
        )

    def test_todos_can_be_combined_with_each_export_mode(self):
        for flags in ({}, {"courses_only": True}, {"exams_only": True}):
            with self.subTest(flags=flags):
                ics, _ = self.generate(include_todos=True, **flags)
                self.assertEqual(ics.count("测试课程 - 测试作业"), 1)
                self.assertEqual(ics.count("[务必核对!]"), 0 if flags.get("courses_only") else 1)

    def test_todos_are_opt_in(self):
        self.generate()
        self.client.r.get.assert_not_called()

    def test_all_terms_combine_with_filters_and_todos(self):
        config.loadAll()
        ics, _ = self.generate(courses_only=True, include_todos=True)
        self.assertNotIn("务必核对", ics)
        self.assertEqual(ics.count("测试课程 - 测试作业"), 1)
        for year in range(2022, 2027):
            self.assertIn(f"DTSTART;TZID=Asia/Shanghai:{year}", ics)

    def test_legacy_positional_signature_and_tuple_return(self):
        ics, filename = getCalender("3000000000", "offline", False, True, False)
        self.assertEqual(ics.count("BEGIN:VEVENT"), 1)
        self.assertTrue(filename.endswith("考试安排.ics"))

    def test_cli_export_matrix_with_real_calendar_pipeline(self):
        with tempfile.TemporaryDirectory() as folder:
            for all_terms in (False, True):
                for mode in (None, "--exams-only", "--courses-only"):
                    for include_todos in (False, True):
                        with self.subTest(all_terms=all_terms, mode=mode, todos=include_todos):
                            target = Path(folder) / "calendar.ics"
                            args = [
                                "-u",
                                "3000000000",
                                "-p",
                                "offline",
                                "-o",
                                str(target),
                                "-f",
                                "--delay",
                                "0",
                            ]
                            if all_terms:
                                args.append("--all")
                            if mode:
                                args.append(mode)
                            if include_todos:
                                args.append("--include-todos")
                            zjuical.main(args)
                            ics = target.read_bytes().decode("utf-8")
                            self.assertIn("BEGIN:VCALENDAR\r\n", ics)
                            self.assertEqual(
                                "SUMMARY;LANGUAGE=zh-cn:测试课程\r\n" in ics, mode != "--exams-only"
                            )
                            self.assertEqual(
                                ics.count("[务必核对!]"), 0 if mode == "--courses-only" else 1
                            )
                            self.assertEqual(ics.count("测试课程 - 测试作业"), int(include_todos))

    def test_filename_sanitizes_reserved_characters(self):
        self.client.student_info = {"xm": '测/试\\姓:名*?"<>|'}
        _, filename = self.generate()
        self.assertTrue(filename.startswith("测_试_姓_名______"))
        self.assertFalse(any(char in filename for char in '/\\:*?"<>|'))

    def test_no_student_info_falls_back_to_term_name(self):
        self.client.r.post.side_effect = lambda *a, **kw: response({"kbList": []})
        _, filename = self.generate(courses_only=True)
        self.assertEqual(filename, "2026-2027 秋冬课程表.ics")

    def test_legacy_skip_verification_for_unknown_id(self):
        getCalender("other", "offline", True, courses_only=True)
        self.factory.assert_called_once_with("other", "offline", 1.5)

    def test_explicit_login_method_and_delay(self):
        grs = patch("main.integration.GrsZjuam", return_value=self.client).start()
        getCalender("other", "offline", skip_verification_and_use="grs", request_delay=0.25)
        grs.assert_called_once_with("other", "offline", 0.25)
        self.factory.assert_not_called()

    def test_invalid_inputs_fail_before_login(self):
        for kwargs in (
            {"exams_only": True, "courses_only": True},
            {"skip_verification_and_use": "bad"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.generate(**kwargs)
        with self.assertRaises(ValueError):
            getCalender("", "offline")
        with self.assertRaises(NotImplementedError):
            getCalender("unknown", "offline")
        self.client.login.assert_not_called()


class CourseAndResponseTests(OfflineTest):
    def setUp(self):
        super().setUp()
        config.load(str(ROOT / "configs/config.json"))
        self.client = UgrsZjuam("3000000000", "offline", 0.25)
        self.client.r = Mock()
        self.sleep = patch("time.sleep").start()

    def fetch(self, content, **kwargs):
        self.client.r.post.return_value = response(content, **kwargs)
        return self.client.getCourses("2026-2027", Term.Autumn, ExamTable())

    def test_short_kcb_preserves_teacher_and_location_fallbacks(self):
        course = UGRSCourse(raw_course(kcb="测试课程<br>1-8周"))
        self.assertEqual(course.teacher, "未知教师")
        self.assertEqual(course.location, "未知地点")
        course = UGRSCourse(raw_course(kcb="测试课程<br>1-8周<br>测试教师"))
        self.assertEqual(course.teacher, "测试教师")
        self.assertEqual(course.location, "未知地点")

    def test_empty_location_still_serializes_calendar(self):
        table = self.fetch({"kbList": [raw_course(kcb="测试课程<br>1-8周<br>测试教师<br>")]})
        from ical.ical import Calender

        cal = Calender()
        cal.addEvents(table.toEvents(config.termConfigs[0]))
        self.assertIn("BEGIN:VEVENT", cal.getICS())

    def test_courses_with_no_exams_do_not_crash(self):
        table = UGRSCourseTable()
        table.fromRes([raw_course()])
        table.communicate(None)
        self.assertIsNone(table.courses[0].credit)

    def test_duplicate_and_adjacent_courses_merge(self):
        table = self.fetch({"kbList": [raw_course(), raw_course(), raw_course(djj="3")]})
        self.assertEqual(len(table.courses), 1)
        self.assertEqual((table.courses[0].start, table.courses[0].end), (1, 5))

    def test_different_locations_remain_separate(self):
        table = self.fetch(
            {"kbList": [raw_course(), raw_course(kcb="测试课程<br>1-8周<br>测试教师<br>东2-202")]}
        )
        self.assertEqual(len(table.courses), 2)

    def test_json_string_response_and_student_info(self):
        table = self.fetch(json.dumps({**STUDENT, "kbList": [raw_course()]}))
        self.assertEqual(len(table.courses), 1)
        self.assertEqual(self.client.student_info, STUDENT)
        self.sleep.assert_called_once_with(0.25)

    def test_html_errors_are_detected_before_json(self):
        for html in (
            "<!doctype html><title>错误提示</title>",
            "  <!DOCTYPE HTML><html>",
            "<html>过期</html>",
        ):
            with self.subTest(html=html), self.assertRaisesRegex(Exception, "HTML 错误页面"):
                self.fetch({}, text=html)
            self.client.r.post.return_value.json.assert_not_called()

    def test_captcha_response_is_detected(self):
        for content in ("captcha required", "CAPTCHA", "需要验证码"):
            with self.subTest(content=content), self.assertRaisesRegex(ValueError, "验证码"):
                self.fetch(content)

    def test_invalid_response_shapes_fail_clearly(self):
        for content, message in (
            ([], "期望 dict"),
            ({}, "缺少 kbList"),
            ({"kbList": {}}, "必须是列表"),
            ("invalid json", "无法解析"),
        ):
            with self.subTest(content=content), self.assertRaisesRegex(Exception, message):
                self.fetch(content)

    def test_exam_request_respects_delay(self):
        self.client.r.post.return_value = response({"items": [raw_exam()]})
        table = self.client.getExams()
        self.assertEqual(len(table.exams), 1)
        self.sleep.assert_called_once_with(0.25)

    def test_user_agent_is_preserved(self):
        client = UgrsZjuam("3000000000", "offline")
        self.assertIn("Mozilla/5.0", client.r.headers["User-Agent"])


class ConfigAndUpstreamTests(OfflineTest):
    def test_autumn_holidays_move_and_exchange_courses(self):
        config.load(str(ROOT / "configs/config.json"))
        for weekday, target, canceled in (
            (5, "2026-10-17", "2026-10-02"),
            (2, "2026-09-20", "2026-10-06"),
            (3, "2026-10-10", "2026-10-07"),
        ):
            with self.subTest(weekday=weekday):
                table = UGRSCourseTable()
                table.fromRes([raw_course(xqj=str(weekday))])
                dates = {
                    event.start.date().isoformat()
                    for event in table.toEvents(config.termConfigs[0])
                }
                self.assertIn(target, dates)
                self.assertNotIn(canceled, dates)

    def test_current_term_dates_and_holiday_makeup(self):
        config.load(str(ROOT / "configs/config.json"))
        self.assertEqual(config.toTermString(), "2026-2027 秋冬")
        self.assertEqual(config.termConfigs[1].Begin, datetime(2026, 11, 9))
        table = UGRSCourseTable()
        table.fromRes([raw_course(xqj="4")])
        events = table.toEvents(config.termConfigs[1])
        dates = {event.start.date().isoformat() for event in events}
        self.assertNotIn("2026-12-31", dates)
        self.assertIn("2027-01-04", dates)

    def test_all_configs_load_without_duplicate_terms(self):
        cfg = Config()
        cfg.loadAll()
        self.assertEqual(len(cfg.classTerms), 18)
        self.assertEqual(len({(ct.Year, ct.Term) for ct in cfg.classTerms}), 18)
        self.assertEqual(len(cfg.termConfigs), 18)
        self.assertEqual(cfg.lastUpdated, datetime(2026, 9, 17))
        cfg.load(str(ROOT / "configs/config.json"))
        self.assertFalse(cfg.is_all)
        self.assertEqual(len(cfg.classTerms), 2)

    def test_every_config_can_generate_course_events(self):
        for path in sorted((ROOT / "configs").glob("config*.json")):
            with self.subTest(path=path.name):
                config.load(str(path))
                table = UGRSCourseTable()
                table.fromRes([raw_course()])
                for term in config.termConfigs:
                    self.assertTrue(table.toEvents(term))

    def test_graduate_academic_year_always_uses_start_year(self):
        client = GrsZjuam("1000000000", "offline", 0)
        client._token = "offline-token"
        client.r = Mock()
        client.r.get.return_value = response({"success": True, "result": {"kcbMap": {}}})
        client.r.post.return_value = response({"success": True, "result": {"xxjhnList": []}})
        with patch("time.sleep"):
            for term in (Term.Autumn, Term.Winter, Term.Spring, Term.Summer):
                with self.subTest(term=term):
                    client.getCourses("2026-2027", term, ExamTable())
                    self.assertIn("xn=2026&", client.r.get.call_args.args[0])
        self.assertEqual(client.getExams().exams, [])

    def test_todos_filter_and_deadline_conversion(self):
        table = TodoTable()
        table.fromRes([raw_todo(), raw_todo(is_student=False)])
        self.assertEqual(len(table.todos), 1)
        event = table.toEvents(ExamTable())[0]
        self.assertEqual(event.summary, "测试课程 - 测试作业")
        self.assertIsNone(event.end)
        self.assertEqual(
            event.start.timestamp(), datetime.fromisoformat("2026-11-10T08:00:00+00:00").timestamp()
        )


class CliAndWebTests(OfflineTest):
    ARGS = ["-u", "3000000000", "-p", "offline"]

    def test_new_and_legacy_flags_coexist(self):
        args = zjuical.parse_args(
            [
                *self.ARGS,
                "--all",
                "--courses-only",
                "--include-todos",
                "--delay",
                "0",
                "--skip-verification",
            ]
        )
        self.assertTrue(
            args.all and args.courses_only and args.include_todos and args.skip_verification
        )
        self.assertEqual(args.delay, 0)
        self.assertIsNone(args.output)

    def test_conflicting_filters_and_invalid_delays_are_rejected(self):
        for extra in (
            ["--exams-only", "--courses-only"],
            ["--delay", "-1"],
            ["--delay", "nan"],
            ["--delay", "inf"],
        ):
            with (
                self.subTest(extra=extra),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as cm,
            ):
                zjuical.parse_args([*self.ARGS, *extra])
            self.assertEqual(cm.exception.code, 2)

    def test_cli_generates_dynamic_filename_and_respects_overwrite(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.chdir(folder):
            patch("zjuical.config.load").start()
            patch("zjuical.getCalender", return_value=("日历内容", "动态文件名.ics")).start()
            zjuical.main(self.ARGS)
            target = Path("动态文件名.ics")
            self.assertEqual(target.read_text(encoding="utf-8"), "日历内容")
            target.write_text("已有内容", encoding="utf-8")
            with self.assertRaises(SystemExit):
                zjuical.main(self.ARGS)
            self.assertEqual(target.read_text(encoding="utf-8"), "已有内容")
            zjuical.main([*self.ARGS, "-f"])
            self.assertEqual(target.read_text(encoding="utf-8"), "日历内容")

    def test_cli_explicit_output_and_all_options_reach_integration(self):
        with tempfile.TemporaryDirectory() as folder:
            load_all = patch("zjuical.config.loadAll").start()
            load = patch("zjuical.config.load").start()
            generate = patch("zjuical.getCalender", return_value=("ICS", "ignored.ics")).start()
            target = Path(folder) / "指定路径.ics"
            zjuical.main(
                [
                    *self.ARGS,
                    "-a",
                    "-o",
                    str(target),
                    "--exams-only",
                    "--include-todos",
                    "--delay",
                    "0.2",
                    "--skip-verification-and-use",
                    "ugrs",
                ]
            )
            self.assertEqual(target.read_text(), "ICS")
            load_all.assert_called_once()
            load.assert_not_called()
            self.assertEqual(
                generate.call_args.kwargs,
                {
                    "exams_only": True,
                    "courses_only": False,
                    "skip_verification_and_use": "ugrs",
                    "request_delay": 0.2,
                    "include_todos": True,
                },
            )

    def test_web_subscription_keeps_fixed_output_by_default(self):
        run = patch("webical.subprocess.run").start()
        with contextlib.redirect_stdout(io.StringIO()):
            webical.run_zjuical("-u 3000000000 -p 'offline with spaces' -f --courses-only")
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[-2:], ["-o", "zjuical.ics"])
        self.assertIn("offline with spaces", cmd)

    def test_web_preserves_explicit_output(self):
        run = patch("webical.subprocess.run").start()
        for output in (
            "-o custom.ics",
            "--output custom.ics",
            "--output=custom.ics",
            "-ocustom.ics",
        ):
            with self.subTest(output=output), contextlib.redirect_stdout(io.StringIO()):
                webical.run_zjuical("-u 3000000000 -p offline " + output)
                self.assertNotIn("zjuical.ics", run.call_args.args[0][2:])

    def test_web_serves_utf8_calendar(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.chdir(folder):
            Path("zjuical.ics").write_text(
                "BEGIN:VCALENDAR\r\n测试课程\r\nEND:VCALENDAR", encoding="utf-8"
            )
            reply = webical.app.test_client().get("/zjuical.ics")
            self.assertEqual(reply.status_code, 200)
            self.assertIn("测试课程", reply.get_data(as_text=True))
            self.assertEqual(reply.mimetype, "text/calendar")


if __name__ == "__main__":
    unittest.main()
