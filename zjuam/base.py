import requests
from course.course import CourseTable
from exam.exam import ExamTable
from utils.const import Term
from abc import ABC, abstractmethod


class Zjuam(ABC):
    LOGIN_URL = "https://zjuam.zju.edu.cn/cas/login"
    PUBKEY_URL = "https://zjuam.zju.edu.cn/cas/v2/getPubKey"

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.r = requests.Session()
        # 使用与模拟脚本一致的 User-Agent
        self.r.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        })
        # 存储用户信息
        self.student_info = {}

    @abstractmethod
    def login(self) -> None:
        pass

    @abstractmethod
    def getCourses(self, year: str, term: Term, exams: ExamTable) -> CourseTable:
        pass
