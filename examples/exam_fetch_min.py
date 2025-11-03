# Minimal exam fetch & ICS export.
# Requires: pip install requests>=2.32.3
# Env: export ZJU_USERNAME=... ZJU_PASSWORD=...

import os, re, time
from datetime import datetime
from pathlib import Path

import requests

LOGIN_FORM_URL = "https://zjuam.zju.edu.cn/cas/login?service=https%3A%2F%2Fzdbk.zju.edu.cn%2Fjwglxt%2Fxtgl%2Flogin_ssologin.html"
LOGIN_POST_URL = "https://zjuam.zju.edu.cn/cas/login"
PUBKEY_URL = "https://zjuam.zju.edu.cn/cas/v2/getPubKey"
EXAM_URL = "https://zdbk.zju.edu.cn/jwglxt/xskscx/kscx_cxXsgrksIndex.html?doType=query&gnmkdm=N509070&su=%s"

def rsa_encrypt(password, modulus_hex, exponent_hex):
    n = int(modulus_hex, 16)
    e = int(exponent_hex, 16)
    m = int.from_bytes(password.encode(), "big")
    return f"{pow(m, e, n):0128x}"

def parse_exam_time(raw):
    if not raw or "考试第" in raw:
        return None, None
    date = raw[:11]
    start = datetime.strptime(date + raw[12:17], "%Y年%m月%d日%H:%M")
    end = datetime.strptime(date + raw[18:23], "%Y年%m月%d日%H:%M")
    return start, end

def login(session, username, password):
    csrf_page = session.get(LOGIN_FORM_URL)
    csrf_page.raise_for_status()
    csrf = re.search(r'"execution" value="(.*?)"', csrf_page.text).group(1)
    pub = session.get(PUBKEY_URL).json()
    cipher = rsa_encrypt(password, pub["modulus"], pub["exponent"])
    res = session.post(
        LOGIN_POST_URL,
        data={
            "username": username,
            "password": cipher,
            "authcode": "",
            "execution": csrf,
            "_eventId": "submit",
        },
    )
    res.raise_for_status()
    if "用户名或密码错误" in res.text:
        raise ValueError("Invalid credentials")
    if "账号被锁定" in res.text:
        raise ValueError("Account locked")
    return session

def fetch_exams(session, username):
    payload = {
        "_search": "false",
        "nd": str(int(time.time() * 1000)),
        "queryModel.showCount": "5000",
        "queryModel.currentPage": "1",
        "queryModel.sortName": "xkkh",
        "queryModel.sortOrder": "asc",
        "time": "0",
    }
    resp = session.post(EXAM_URL % username, data=payload)
    resp.raise_for_status()
    exams = []
    for item in resp.json().get("items", []):
        name = item["kcmc"].replace("(", "（").replace(")", "）")
        base = {"name": name, "class_id": item["xkkh"][:22], "credit": float(item["xf"])}
        for key, exam_type, loc_key, seat_key in (
            ("kssj", "期末考试", "jsmc", "zwxh"),
            ("qzkssj", "期中考试", "qzjsmc", "qzzwxh"),
        ):
            if key in item:
                start, end = parse_exam_time(item.get(key))
                exams.append(
                    {
                        **base,
                        "type": exam_type,
                        "start": start,
                        "end": end,
                        "location": item.get(loc_key),
                        "seat": item.get(seat_key),
                    }
                )
        if "kssj" not in item and "qzkssj" not in item:
            exams.append({**base, "type": "无考试", "start": None, "end": None, "location": None, "seat": None})
    return exams

def to_ics(exams, calendar_name="ZJU Exams"):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"X-WR-CALNAME:{calendar_name}",
        "PRODID:-//ZJU-ICAL-PY//Minimal//EN",
        "BEGIN:VTIMEZONE",
        "TZID:Asia/Shanghai",
        "END:VTIMEZONE",
    ]
    for exam in exams:
        if not (exam["start"] and exam["end"]):
            continue
        start = exam["start"].strftime("%Y%m%dT%H%M%S")
        end = exam["end"].strftime("%Y%m%dT%H%M%S")
        seat = f" (座位: {exam['seat']})" if exam["seat"] else ""
        location = exam["location"] or "地点待定"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"SUMMARY:[务必核对!]{exam['name']} {exam['type']}",
                f"DTSTART;TZID=Asia/Shanghai:{start}",
                f"DTEND;TZID=Asia/Shanghai:{end}",
                f"LOCATION:{location}{seat}",
                f"DESCRIPTION:学分 {exam['credit']:.1f}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"

def main():
    username = os.environ["ZJU_USERNAME"]
    password = os.environ["ZJU_PASSWORD"]
    session = login(requests.Session(), username, password)
    exams = fetch_exams(session, username)
    Path("zju_exams.ics").write_text(to_ics(exams, "最新考试安排"), encoding="utf-8")
    print(f"Fetched {len(exams)} exam entries; wrote zju_exams.ics")


if __name__ == "__main__":
    main()
