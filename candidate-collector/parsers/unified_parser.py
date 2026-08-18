"""Unified resume document parser.

Extracts text from PDF, DOC, DOCX and image files, then applies conservative
regex-based field extraction to produce a :class:`models.CandidateRecord`.

This module intentionally does **not** use LLMs to invent missing fields.  Low
confidence or missing fields are left as ``None`` or marked for review.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from models import CandidateRecord, Education, FieldConfidence, WorkExperience

if TYPE_CHECKING:
    from parsers.mosaic_phone_recovery import RecoveryResult


SUPPORTED_OFFICE = {".doc", ".docx"}
SUPPORTED_IMAGES = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}
SUPPORTED_EXTENSIONS = {".pdf"} | SUPPORTED_OFFICE | SUPPORTED_IMAGES

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
# Chinese mobile phones: 11 digits starting with 1.
PHONE_RE = re.compile(r"(?<![\d])1[3-9]\d{9}(?![\d])")
# Fallback generic phone.
PHONE_GENERIC_RE = re.compile(r"(?<![\d])\d{7,15}(?![\d])")

SCHOOL_RE = re.compile(r"([^\n]{2,20}(?:大学|学院|分校|研究院|School|University|College))")
DEGREE_RE = re.compile(r"(本科|硕士|博士|大专|专科|MBA|EMBA|研究生|学士|Bachelor|Master|Ph\.?D)")
# Graduation year: require an explicit 毕业/届 marker to avoid matching any 20xx year.
GRAD_YEAR_RE = re.compile(r"(20\d{2})\s*年?\s*(?:毕业|届)")

CITY_LIST = [
    "北京", "上海", "深圳", "广州", "杭州", "成都", "苏州", "南京", "重庆",
    "武汉", "西安", "天津", "长沙", "郑州", "沈阳", "青岛", "合肥", "佛山",
    "宁波", "东莞", "无锡", "济南", "厦门", "福州", "昆明", "南宁", "哈尔滨",
    "长春", "大连", "南昌", "贵阳", "海口", "兰州", "乌鲁木齐", "西宁", "银川",
]

EMPLOYMENT_STATUS_KEYWORDS = {
    "在职-暂不考虑": "在职-暂不考虑",
    "在职-考虑机会": "在职-考虑机会",
    "在职": "在职",
    "离职-随时到岗": "离职-随时到岗",
    "离职": "离职",
    "正在找工作": "正在找工作",
    "看机会": "看机会",
}

# Multiple Chinese date formats commonly found in resumes.
PERIOD_PATTERNS = [
    # 2020.03 - 2021.05 / 2020.03 - 至今 / 2020.3 - 至今
    r"(?:19|20)\d{2}(?:\.\d{1,2})?\s*[-–—至～~]\s*(?:至今|(?:19|20)\d{2}(?:\.\d{1,2})?)",
    # 2020年3月 - 2021年5月 / 2020年 3月 - 至今
    r"(?:19|20)\d{2}年\s*\d{1,2}月\s*[-–—至～~]\s*(?:至今|(?:19|20)\d{2}年\s*\d{1,2}月)",
    # 2020/03 - 2021/05 / 2020-03 - 至今
    r"(?:19|20)\d{2}[/\-]\d{1,2}\s*[-–—至～~]\s*(?:至今|(?:19|20)\d{2}[/\-]\d{1,2})",
    # 2020 - 2021 / 2020 - 至今
    r"(?:19|20)\d{2}\s*[-–—至～~]\s*(?:至今|(?:19|20)\d{2})",
]
PERIOD_RE = re.compile("|".join(f"({p})" for p in PERIOD_PATTERNS))

ROLE_KEYWORDS_RE = re.compile(
    r"(工程师|经理|总监|负责人|顾问|专员|主管|架构师|分析师|产品经理|运营|开发|设计师|研究员|教师|实习生|副总裁|总裁|CEO|COO|CTO|CFO|VP|合伙人|创始人|董事长|总经理|总监|副总监|高级|资深|助理|秘书|代表|销售|市场|品牌|战略|投资|咨询|采购|供应链|人事|行政|财务|法务|公关|媒介|内容|编辑|记者|主播|运营|客服|物流|仓储|生产|制造|质量|工艺|项目经理|产品经理|数据|算法|前端|后端|客户端|测试|运维|安全|DBA|全栈|嵌入式|硬件|芯片|算法|科学家|研究员|教授|讲师|医生|护士|药师|律师|会计师|审计师|税务师|经济师|统计师|建筑师|设计师|规划师|咨询师|评估师|造价师|建造师|监理|护士|护师|营养师|心理咨询师|培训师|教练|翻译|导游|司机|厨师|服务员|保安|保洁|销售|顾问|经纪人|代理人|记者|编辑|主持|编导|制片|导演|演员|歌手|模特|运动员|教练|裁判| librarian|教师|助教|辅导员|校长|园长|所长|院长|主任|科长|处长|局长|司长|部长|省长|市长|县长|区长|镇长|乡长|村长|书记|主席|常委|委员|代表|议员|大使|领事|参赞|武官|特务|间谍|警察|法官|检察官|律师|公证员|仲裁员|调解员|狱警|法医|消防员|军人|士兵|军官|将军|元帅|司令|政委|参谋长|师长|旅长|团长|营长|连长|排长|班长|舰长|机长|船长|车长|站长|段长|所长|队长|组长|线长|工段长|领班|主管|经理|总监|副总|总经理|总裁|董事长|CEO|COO|CFO|CTO|CMO|CHO|CIO|CKO|CSO|CCO|CRO|CLO|CPO|CQO|CVO|CXO)"
)

INVALID_COMPANY_RE = re.compile(
    r"(大学|学院|分校|研究院|本科|硕士|博士|大专|专科|毕业|姓名|电话|邮箱|个人简历|在线简历|工作经历|教育经历|项目经历|求职意向|联系方式|自我评价|个人优势|技能专长|荣誉证书|兴趣爱好|主修课程|培训经历|语言能力|获得奖项|发表文章|专利|作品集)"
)

# Lines that begin with responsibility verbs are descriptions, not companies.
RESPONSIBILITY_PREFIX_RE = re.compile(
    r"^(负责|参与|主导|完成|承担|协助|配合|组织|协调|推动|跟进|管理|支持|提供|实现|建立|"
    r"制定|策划|执行|落实|优化|提升|拓展|维护|开发|设计|研究|分析|总结|撰写|编制|审核|"
    r"对接|沟通|谈判|销售|采购|生产|运营|推广|编辑|发布|测试|上线|部署|监控|排查|解决|"
    r"处理|服务|培训|指导|带领|项目|产品|客户|用户|渠道|市场|品牌|公关|媒介|内容|社群|"
    r"活动|会议|报告|方案|计划|流程|制度|标准|规范|体系|平台|系统|工具|模型|算法|数据|"
    r"接口|模块|功能|页面|交互|视觉|原型|文档|手册|教程|案例|样本|信息|资料|文件|材料|"
    r"证据|依据|参考|说明|备注|注释|反馈|评价|评分|排名|榜单)"
)

# UI chrome / boilerplate full-line labels leaked from recruiting-site pages
# (BOSS 直聘, 脉脉). These never appear as a standalone line in a real resume,
# so dropping them keeps them out of name/company/experience extraction and
# out of raw_text.
NOISE_LINE_EXACT = {
    "展开", "收起", "加载更多", "查看更多", "展开全部",
    "该段经历来自附件简历",
    "人才已投递职位，期待处理：",
    "快捷回复", "通过初筛", "不合适", "下载在线简历", "转发给同事",
    "加好友", "加入储备", "特别关注", "加入其他职位", "查看邮箱",
    "请输入备注内容", "暂无备注内容", "正在写入云端人才库…",
}
NOISE_LINE_RE = re.compile(r"^(?:[Tt][Aa]有\d+个好友在此(?:公司|学校)|备注（\d+）)$")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_pdf_text(path: Path) -> str:
    # PyMuPDF is intentionally lazy-loaded so the browser-text cloud gateway
    # does not need the heavy local-file/OCR dependency set.
    import fitz

    doc = fitz.open(path)
    parts: list[str] = []
    for page in doc:
        text = page.get_text("text").strip()
        if text:
            parts.append(text)
    doc.close()
    return "\n".join(parts)


def _extract_office_text(path: Path) -> str:
    """Use macOS textutil to convert DOC/DOCX to plain text."""
    try:
        result = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            check=True,
            capture_output=True,
            timeout=60,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    return result.stdout.decode("utf-8", errors="replace").strip()


def _extract_image_text(path: Path) -> tuple[str, float, str]:
    """Run OCR on an image resume.

    Returns (text, confidence, engine).  Falls back to empty text if OCR is not
    available so the caller can mark the record as needing review.
    """
    try:
        from image_processing.ocr import ocr_pdf

        result = ocr_pdf(path, filetype=path.suffix.lstrip("."), engine="auto")
        return result.text, result.confidence, result.engine
    except Exception:
        return "", 0.0, "none"


def _clean_text(text: str) -> str:
    text = text.replace(" ", " ").replace("​", "")
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        # Drop recruiting-site UI chrome / boilerplate (BOSS, 脉脉).
        if line in NOISE_LINE_EXACT or NOISE_LINE_RE.match(line):
            continue
        # Drop consecutive duplicates only; preserve repeated fragments such as
        # "科技有限公司" that appear under multiple work experiences.
        if lines and line == lines[-1]:
            continue
        lines.append(line)
    return "\n".join(lines)


NAME_STOP_WORDS = {
    "北京", "上海", "深圳", "广州", "杭州", "成都", "苏州", "南京",
    "简历", "个人", "在线", "最新", "版本", "最终", "正式", "工作", "经验", "年限",
    "基本信息", "基础信息", "本科", "硕士", "博士", "大专", "专科", "高中",
}


def _extract_name(text: str, filename: str = "") -> str | None:
    # Try filename patterns first: 【岗位_地点_薪资】姓名_年限.pdf
    m = re.search(r"[】\]]\s*([一-鿿·]{2,6})(?:\s*[-_ ]?\s*\d+年)?(?:\.pdf|\.docx?)?$", filename)
    if m:
        return m.group(1)
    # 简历_姓名.pdf / 个人简历_姓名.pdf
    m = re.search(r"简历[_\-]?([一-鿿·]{2,6})(?:\.pdf|\.docx?)?$", filename, re.I)
    if m:
        return m.group(1)
    # 姓名_简历.pdf / 姓名_个人简历.pdf
    m = re.search(r"^([一-鿿·]{2,6})[-_](?:个人简历|简历)(?:\.pdf|\.docx?)?$", filename, re.I)
    if m:
        return m.group(1)
    # Name as the last Chinese segment before extension, e.g. any_张佩柔.pdf
    m = re.search(r"[-_]([一-鿿·]{2,6})(?:\.pdf|\.docx?)?$", filename, re.I)
    if m and m.group(1) not in NAME_STOP_WORDS:
        return m.group(1)
    # Browser pages and exported profiles often render the name as a labeled
    # field instead of a standalone heading, for example ``姓名：张三``.
    m = re.search(
        r"(?:^|\n)\s*(?:姓名|名字|候选人)\s*[:：]\s*([一-鿿·]{2,6})(?=\s|$)",
        text,
    )
    if m and m.group(1) not in NAME_STOP_WORDS:
        return m.group(1)
    # Look for a standalone 2-4 character Chinese name near the top.
    section_boundaries = {"工作经历", "教育经历", "项目经历", "求职意向", "个人优势", "经历概览", "技能专长", "求职期望"}
    stop = {
        "在线简历", "个人简历", "求职简历", "我的简历", "简历模板", "应聘简历", "简历", "基本信息", "基础信息",
        "本科", "硕士", "博士", "大专", "专科", "高中",
        # 脉脉单独成行的学历/标签词（远程修复引入，合并保留）
        "研究生", "学士", "中专", "职业标签", "更多资料", "实名动态", "自我评价",
        # BOSS 面板 UI 标签/按钮，绝不可能是姓名（历史脏数据教训：全文/转发 曾被当姓名入库）
        "全文", "转发", "不合适", "打招呼", "更换职位沟通", "经历概览",
        "附件简历", "展开", "收起", "立即沟通", "聊一聊", "招聘规范",
        # TTC 人才库页面 UI 按钮/标签（历史脏数据：「加入名单」曾被当姓名入库）
        "加入名单", "快速推荐", "人才库插件", "返回TTC人才库", "水下信息",
        "画像", "推荐报告", "重复信息", "更新记录", "备注", "投递", "加载中", "添加亮点总结",
        # TTC 页面的院校分层标签与字段标签
        "双一流", "985", "211", "QS 100", "QS 500", "年龄", "未知", "海外工作经验", "管理经验",
    }
    for line in text.splitlines()[:30]:
        line = line.strip()
        if line in section_boundaries:
            break
        if line in stop or "简历" in line:
            continue
        # TTC 页面脱敏姓名：骆女士|路女士 / 王先生（竖线分隔男女未知两种写法）
        if re.fullmatch(r"[一-鿿·]{1,4}(?:女士|先生)([|｜][一-鿿·]{1,4}(?:女士|先生))?", line):
            return line
        # 真实姓名绝不含这些词根（TTC 标签行：留学经验/管理经验/0-1项目经验…）
        if re.search(r"(经验|项目|管理|标签|经历|技能|留学|工作|教育|培训|语言|荣誉|证书|优势|评价|意向|期望|创业|出海|海外|信息|资料)", line):
            continue
        if re.fullmatch(r"[一-鿿·]{2,4}", line):
            # A bare 2-4 char line is a name only if it isn't a section header,
            # degree, role, or company-ish token (脉脉 puts "本科"/"销售总监" here).
            if ROLE_KEYWORDS_RE.search(line) or INVALID_COMPANY_RE.search(line):
                continue
            return line
        # Name followed by " 男 28岁" etc. Require at least one digit so plain
        # 2-4 character lines are not mis-identified as names.
        m = re.match(r"([一-鿿·]{2,4})\s*[男女]?\s*\d{1,2}", line)
        if m and not re.search(r"(职位|公司|学校|专业|经验|北京|上海|深圳|广州)", line):
            return m.group(1)
    return None


def _match_period(line: str) -> re.Match | None:
    return PERIOD_RE.search(line)


def _extract_period(line: str) -> str:
    m = _match_period(line)
    return m.group(0) if m else ""


def _looks_like_role(line: str) -> bool:
    return (
        bool(line)
        and 2 <= len(line) <= 20
        and bool(ROLE_KEYWORDS_RE.search(line))
        and not _match_period(line)
        and not re.search(r"[@%｜|]|\d{7,}|[，,。；;：:]", line)
    )


def _looks_like_company(line: str) -> bool:
    #  strip private-use-area glyphs（PDF 项目符号残留）再判断
    line = re.sub(r"[-]", "", line).strip()
    if not line or not (2 <= len(line) <= 25):
        return False
    # 公司名不含：邮箱/电话/百分比/竖线/句读——这些是联系方式行或整句业绩被误识别
    if re.search(r"[@%｜|]|\d{7,}|[，,。；;：:、]", line):
        return False
    # 时长行（（1.2年））、纯数字标点（6. / 03）、散文碎片（…等）、版块标签（重复信息）
    if re.fullmatch(r"[（(][\d.]+\s*年?[）)]", line) or re.fullmatch(r"[\d./\s]+", line):
        return False
    if line.endswith("等") or "兼职" in line or line in {"重复信息", "个人信息", "自我评价", "个人项目", "个人优势"}:
        return False
    # 括号不配对 = 句子被截断的碎片（如「初创公司（专注海外多模态」）
    if line.count("（") != line.count("）") or line.count("(") != line.count(")"):
        return False
    # 城市名不是公司
    if line in CITY_LIST or line in {"西雅图", "旧金山", "纽约", "洛杉矶", "硅谷", "伦敦", "新加坡", "东京"}:
        return False
    if INVALID_COMPANY_RE.search(line) or _match_period(line):
        return False
    if ROLE_KEYWORDS_RE.search(line):
        # 公司名常含职位词根（品牌战略咨询/启承资本/创投基金）：去掉公司后缀后
        # 整体仍是一个职位词的才否决（如「战略咨询」「产品经理」独行）
        m = re.match(r"^(.+?)(有限公司|有限责任公司|股份有限公司|公司|集团|咨询|科技|网络|信息|投资|合伙|工作室|事务所|中心|研究院|企业|实业|控股|基金|资本)$", line)
        if not m or ROLE_KEYWORDS_RE.fullmatch(m.group(1).strip()):
            return False
    if RESPONSIBILITY_PREFIX_RE.match(line):
        return False
    return True


def _looks_like_company_fragment(line: str, next_line: str = "") -> bool:
    """A line that looks like a fragment of a company name when merged with next."""
    if not line or len(line) > 20:
        return False
    if INVALID_COMPANY_RE.search(line) or _match_period(line) or ROLE_KEYWORDS_RE.search(line):
        return False
    if RESPONSIBILITY_PREFIX_RE.match(line):
        return False
    # Fragments should not contain numbers, percentages, or lots of punctuation.
    if re.search(r"[0-9%０-９，,、.。;；:：!！?？]", line):
        return False
    # Common company suffixes that often appear on their own line.
    suffixes = ("有限公司", "有限责任公司", "股份有限公司", "集团", "科技", "网络", "信息", "咨询",
                "投资", "合伙", "工作室", "事务所", "中心", "研究院", "学院", "大学")
    if any(s in next_line for s in suffixes):
        return True
    if any(s in line for s in ("北京", "上海", "深圳", "广州", "杭州", "成都")):
        return True
    return False


def _extract_experiences(text: str) -> tuple[list[WorkExperience], float]:
    """Conservative multi-format experience extraction.

    Handles:
      1. Single-line entries like "公司 职位 2020.03 - 至今".
      2. Multi-line blocks in both orders:
         - 公司 / 周期 / 职位
         - 公司 / 职位 / 周期
      3. Cross-line company names such as "北京字节跳动" + "科技有限公司".

    Returns the list of experiences and an aggregate confidence score.
    """
    entries: list[WorkExperience] = []
    lines = text.splitlines()

    # Find work experience section if present.
    section_start: int | None = None
    section_end = len(lines)
    for idx, line in enumerate(lines):
        if re.search(r"工作(经历|经验)", line):
            section_start = idx + 1
        elif section_start is not None and re.search(r"(教育经历|项目经历|技能专长|求职期望|自我评价|培训经历|语言能力|荣誉证书)", line):
            section_end = idx
            break

    scan_lines = lines[section_start:section_end] if section_start is not None else lines

    # Pass 0: period-first lines such as "2010 — 至今，中页品牌战略咨询"（部分中文简历把
    # 日期放句首，公司跟在逗号后，职位在下一行）。
    for idx, raw_line in enumerate(scan_lines):
        line = raw_line.strip()
        m = PERIOD_RE.match(line)
        if not m:
            continue
        period = m.group(0)
        rest = line[m.end():].strip(" ,，|｜、")
        if not rest:
            continue
        company = ""
        role = ""
        if _looks_like_company(rest):
            company = rest
        else:
            tokens = rest.split()
            if len(tokens) >= 2 and _looks_like_company(" ".join(tokens[:-1])) and _looks_like_role(tokens[-1]):
                company, role = " ".join(tokens[:-1]), tokens[-1]
        if company and not role and idx + 1 < len(scan_lines):
            nxt = scan_lines[idx + 1].strip()
            if _looks_like_role(nxt):
                role = nxt
        if company:
            entries.append(WorkExperience(company=company, role=role, period=period))

    # First pass: single-line entries.
    for line in scan_lines:
        line = line.strip()
        if _match_period(line) and ROLE_KEYWORDS_RE.search(line):
            parts = PERIOD_RE.split(line, maxsplit=1)
            before_period = parts[0].strip().replace("|", " ")
            period = _extract_period(line)
            tokens = before_period.split()
            if len(tokens) >= 2:
                role = tokens[-1]
                company = " ".join(tokens[:-1])
                if _looks_like_company(company):
                    entries.append(WorkExperience(company=company, role=role, period=period))

    # Second pass: multi-line blocks anchored by period lines.
    if not entries:
        period_positions = [i for i, line in enumerate(scan_lines) if _match_period(line)]
        if period_positions:
            consumed: set[int] = set()
            for pos in period_positions:
                if pos in consumed:
                    continue
                period = _extract_period(scan_lines[pos])
                company = ""
                role = ""
                company_pos = -1

                # Look backward for company (and possibly cross-line fragment).
                for j in range(pos - 1, max(pos - 5, -1), -1):
                    if j in consumed:
                        continue
                    line = scan_lines[j].strip()
                    if _looks_like_role(line):
                        # Old order: company / role / period. Keep scanning backward for company.
                        if not role:
                            role = line
                        continue
                    if _looks_like_company(line):
                        company = line
                        company_pos = j
                        # Merge with a preceding fragment if present.
                        if j - 1 >= 0 and (j - 1) not in consumed and _looks_like_company_fragment(scan_lines[j - 1], line):
                            company = scan_lines[j - 1].strip() + company
                            company_pos = j - 1
                        break

                # Look forward for role if not already found behind the period.
                if not role:
                    for j in range(pos + 1, min(pos + 3, len(scan_lines))):
                        if j in consumed:
                            continue
                        line = scan_lines[j].strip()
                        if _looks_like_role(line):
                            role = line
                            consumed.add(j)
                            break

                if company and role:
                    entries.append(WorkExperience(company=company, role=role, period=period))
                    consumed.add(pos)
                    if company_pos >= 0:
                        consumed.add(company_pos)
        else:
            # Fallback heuristic for resumes without explicit periods.  Require a
            # period nearby and a valid company/role pair to avoid matching random
            # adjacent lines.
            i = 0
            while i < len(scan_lines) - 1:
                company = scan_lines[i].strip()
                role = scan_lines[i + 1].strip() if i + 1 < len(scan_lines) else ""
                period = ""
                for j in range(i + 1, min(i + 4, len(scan_lines))):
                    m = _match_period(scan_lines[j].strip())
                    if m:
                        period = m.group(0)
                        break
                if period and _looks_like_company(company) and _looks_like_role(role):
                    entries.append(WorkExperience(company=company, role=role, period=period))
                    i += 3
                    continue
                i += 1

    # Final fallback: section-anchored adjacent pairs with no period anywhere
    # （如「工作经历」节内 公司行 + 职位行 紧挨，日期独立成行在节外）。
    # 只在显式「工作经历」节内启用，避免把随机相邻行当经历。
    if not entries and section_start is not None:
        i = 0
        while i < len(scan_lines) - 1:
            first = scan_lines[i].strip()
            second = scan_lines[i + 1].strip()
            if _looks_like_company(first) and _looks_like_role(second):
                entries.append(WorkExperience(company=first, role=second, period=""))
                i += 2
                continue
            i += 1

    # Deduplicate identical entries: recruiting pages repeat the same block in
    # multiple panels, which otherwise yields duplicate experiences.
    seen: set[tuple[str, str, str]] = set()
    unique_entries: list[WorkExperience] = []
    for e in entries:
        key = (e.company, e.role, e.period)
        if key in seen:
            continue
        seen.add(key)
        unique_entries.append(e)

    # Aggregate confidence for work experience extraction.
    confidence = 0.9 if unique_entries else 0.0
    return unique_entries[:10], confidence


def _extract_labeled_current_work(text: str) -> tuple[str | None, str | None]:
    """Extract explicit current-company/title labels when no dated block exists.

    Browser profile pages often expose summary fields such as ``现任公司：……`` and
    ``职位：……`` without a work-period line.  Those values are useful as current
    profile fields, but must not be promoted to a fabricated WorkExperience.
    """
    company: str | None = None
    title: str | None = None

    company_match = re.search(
        r"^(?:现任|当前)?公司(?:名称)?\s*[：:]\s*([^\n]{2,80})$",
        text,
        re.MULTILINE,
    )
    if company_match:
        company = re.split(
            r"\s+(?:现任|当前)?(?:职位|职务|岗位)\s*[：:]",
            company_match.group(1).strip(),
            maxsplit=1,
        )[0].strip()
        if not company or INVALID_COMPANY_RE.search(company):
            company = None

    title_match = re.search(
        r"^(?:现任|当前)?(?:职位|职务|岗位)\s*[：:]\s*([^\n]{2,80})$",
        text,
        re.MULTILINE,
    )
    if title_match:
        title = re.split(
            r"\s+(?:现任|当前)?公司(?:名称)?\s*[：:]",
            title_match.group(1).strip(),
            maxsplit=1,
        )[0].strip()
        if not title or len(title) > 60:
            title = None

    return company, title


def _extract_education(text: str) -> Education | None:
    lines = text.splitlines()
    school: str | None = None
    degree: str | None = None
    grad_year: int | None = None
    for line in lines:
        school_match = SCHOOL_RE.search(line)
        degree_match = DEGREE_RE.search(line)
        if school is None and school_match:
            school = school_match.group(1).strip()
        if degree is None and degree_match:
            degree = degree_match.group(1)
        # 毕业年份必须与“毕业/届”标记共现；孤立的工作行（如“2020届校招”）不采信。
        if grad_year is None and (school_match or degree_match or "毕业" in line):
            grad_match = GRAD_YEAR_RE.search(line)
            if grad_match:
                grad_year = int(grad_match.group(1))
    # 兜底：含学历词的行内有教育时间段（如“2012-2016 北京大学 本科”）时取结束年。
    if grad_year is None:
        for line in lines:
            if DEGREE_RE.search(line) or "学历" in line:
                years = [int(y) for y in re.findall(r"(?<!\d)(20\d{2})(?!\d)", line)]
                if years:
                    grad_year = max(years)
                    break
    if school is None and degree is None:
        return None
    return Education(school=school, degree=degree, graduation_year=grad_year)


def _infer_expected_location(text: str) -> str | None:
    """Look for an explicit expectation/intention city before falling back."""
    # Lines like: 期望城市：北京 / 意向工作地点：上海 / 期望工作城市：深圳
    pattern = re.compile(r"(?:期望|意向)(?:工作)?(?:城市|地点|工作地点)\s*[：:]\s*([^\n，。；,;]{1,20})")
    for m in pattern.finditer(text):
        candidate = m.group(1).strip()
        for city in CITY_LIST:
            if city in candidate:
                return city
    return None


def _infer_location(text: str) -> str | None:
    for city in CITY_LIST:
        if city in text:
            return city
    return None


def _infer_employment_status(text: str) -> str | None:
    # 按关键词长度降序匹配，保证“在职-考虑机会”等具体状态优先于泛化的“在职”。
    for kw in sorted(EMPLOYMENT_STATUS_KEYWORDS, key=len, reverse=True):
        if kw in text:
            return EMPLOYMENT_STATUS_KEYWORDS[kw]
    return None


def _infer_salary(text: str) -> str | None:
    m = re.search(r"(\d{1,3}\s*[-–—]\s*\d{1,3}\s*[Kk万])", text)
    if m:
        return m.group(1).replace(" ", "")
    m = re.search(r"(期望薪资[：:]\s*\S+)", text)
    if m:
        return m.group(1)
    return None


def _infer_skills(text: str) -> list[str]:
    skills = [
        "Python", "Java", "Go", "C++", "Rust", "JavaScript", "TypeScript", "React", "Vue",
        "Node.js", "Spring", "Django", "Flask", "FastAPI", "Kubernetes", "Docker",
        "Redis", "MySQL", "PostgreSQL", "MongoDB", "Elasticsearch", "Kafka", "RabbitMQ",
        "AWS", "阿里云", "腾讯云", "GCP", "Azure",
        "LLM", "LangChain", "RAG", "Agent", "Transformer", "PyTorch", "TensorFlow",
        "大模型", "机器学习", "深度学习", "自然语言处理", "计算机视觉",
        "产品规划", "用户研究", "数据分析", "SQL", "Tableau", "Figma",
    ]
    # Normalize Chinese punctuation to spaces so skill tokens are separated.
    normalized = text.replace("。", " ").replace("，", " ").replace("、", " ").replace("；", " ").replace("·", " ")
    found = []
    for skill in skills:
        # 不用 \b（中文字符同属单词字符会吃掉边界），改用显式前后断言：
        # “使用Java”可命中，而 JavaScript / Java8 中的 Java 不误命中。
        escaped = re.escape(skill)
        if re.search(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])", normalized, re.IGNORECASE):
            found.append(skill)
    return found


def _build_confidences(
    record: CandidateRecord,
    name_confidence: float,
    ocr_confidence: float,
    exp_confidence: float,
    phone_recovery: "RecoveryResult | None" = None,
) -> list[FieldConfidence]:
    """Populate per-field confidence metadata."""
    confidences: list[FieldConfidence] = []

    def add(field: str, conf: float, note: str | None = None) -> None:
        confidences.append(FieldConfidence(field=field, confidence=round(conf, 2), note=note))

    add("name", name_confidence)
    if phone_recovery and record.phone == phone_recovery.phone:
        add(
            "phone",
            phone_recovery.confidence,
            f"mosaic_recovery ({phone_recovery.source}); {phone_recovery.reasoning or ''}".strip(),
        )
    else:
        add("phone", 1.0 if record.phone else 0.0)
    add("email", 1.0 if record.email else 0.0)

    current_company_conf = 0.0
    current_title_conf = 0.0
    if record.work_experiences:
        current_company_conf = 0.85
        current_title_conf = 0.85
    elif record.current_company:
        current_company_conf = 0.5
    elif record.current_title:
        current_title_conf = 0.5
    add("current_company", current_company_conf, "derived from first work experience" if record.work_experiences else None)
    add("current_title", current_title_conf, "derived from first work experience" if record.work_experiences else None)

    add("work_experiences", exp_confidence)
    add("school", 1.0 if record.school else 0.0)
    add("education", 0.9 if record.education else 0.0)
    add("skills", 0.8 if record.skills else 0.0)
    add("expected_salary", 0.9 if record.expected_salary else 0.0)
    add("current_location", 0.7 if record.current_location else 0.0)

    # Apply OCR confidence multiplier to all fields when OCR was used.
    if ocr_confidence < 1.0:
        for fc in confidences:
            fc.confidence = round(fc.confidence * ocr_confidence, 2)

    return confidences


def _compute_parse_confidence(field_confidences: list[FieldConfidence]) -> float:
    if not field_confidences:
        return 0.0
    # Weighted by business importance.
    weights = {
        "name": 1.0,
        "phone": 1.0,
        "current_company": 0.9,
        "current_title": 0.9,
        "work_experiences": 0.8,
        "school": 0.7,
        "education": 0.6,
        "email": 0.6,
        "skills": 0.5,
        "expected_salary": 0.4,
        "current_location": 0.3,
    }
    total_weight = 0.0
    weighted_sum = 0.0
    for fc in field_confidences:
        w = weights.get(fc.field, 0.5)
        total_weight += w
        weighted_sum += fc.confidence * w
    return round(weighted_sum / total_weight, 2) if total_weight else 0.0


def _estimate_completeness(record: CandidateRecord) -> float:
    total = 10
    present = sum(1 for f in ["name", "phone", "email", "current_company", "current_title", "school", "degree", "raw_text"] if getattr(record, f))
    present += 1 if record.work_experiences else 0
    present += 1 if record.skills else 0
    return round(present / total, 2)


def _post_process_record(
    record: CandidateRecord,
    name_confidence: float,
    ocr_confidence: float,
    exp_confidence: float,
    phone_recovery: "RecoveryResult | None" = None,
) -> CandidateRecord:
    """Derive current company/title, compute confidences and completeness."""
    if record.work_experiences:
        first = record.work_experiences[0]
        if not record.current_company:
            record.current_company = first.company
        if not record.current_title:
            record.current_title = first.role

    record.field_confidences = _build_confidences(record, name_confidence, ocr_confidence, exp_confidence, phone_recovery)
    record.parse_confidence = _compute_parse_confidence(record.field_confidences)

    missing = []
    for field in ["name", "phone", "current_company", "current_title", "school"]:
        if not getattr(record, field):
            missing.append(field)
    record.missing_fields = missing
    record.completeness_score = _estimate_completeness(record)
    return record


def parse_resume_file(path: Path | str) -> CandidateRecord:
    """Parse a local resume file into a CandidateRecord.

    Supports PDF, DOC, DOCX and common image formats.  Image files and scanned
    PDFs are passed through OCR and marked for review when OCR fails.
    """
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file extension: {suffix}")

    sha256 = _sha256_file(path)
    ocr_confidence = 1.0
    ocr_engine = "none"

    if suffix == ".pdf":
        raw_text = _extract_pdf_text(path)
        parser_name = "pymupdf"
        # Fallback to OCR for scanned PDFs.
        if len(raw_text.strip()) < 30:
            ocr_text, ocr_confidence, ocr_engine = _extract_image_text(path)
            if ocr_text:
                raw_text = ocr_text
                parser_name = ocr_engine
    elif suffix in SUPPORTED_OFFICE:
        raw_text = _extract_office_text(path)
        parser_name = "textutil_office"
    elif suffix in SUPPORTED_IMAGES:
        raw_text, ocr_confidence, ocr_engine = _extract_image_text(path)
        parser_name = ocr_engine
    else:
        raw_text = ""
        parser_name = "unknown"

    cleaned = _clean_text(raw_text)
    filename = path.name
    name = _extract_name(cleaned, filename)
    name_confidence = 0.0
    if name:
        name_confidence = 1.0 if filename and name in filename else 0.9
    work_experiences, exp_confidence = _extract_experiences(cleaned)
    labeled_company, labeled_title = _extract_labeled_current_work(cleaned)

    record = CandidateRecord(
        name=name,
        phone=PHONE_RE.search(cleaned).group(0) if PHONE_RE.search(cleaned) else None,
        email=EMAIL_RE.search(cleaned).group(0) if EMAIL_RE.search(cleaned) else None,
        current_company=labeled_company,
        current_title=labeled_title,
        current_location=_infer_location(cleaned),
        employment_status=_infer_employment_status(cleaned),
        expected_salary=_infer_salary(cleaned),
        expected_location=_infer_expected_location(cleaned),
        skills=_infer_skills(cleaned),
        tech_stack=_infer_skills(cleaned),
        work_experiences=work_experiences,
        education=_extract_education(cleaned),
        raw_text=cleaned,
        original_attachment_path=str(path),
        attachment_sha256=sha256,
        attachment_mime_type={
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
        }.get(suffix),
        source_type="local_file",
        source_platform="local_file",
        parser_name=parser_name,
        parser_version="0.1.0",
        review_status="needs_review" if (not cleaned or suffix in SUPPORTED_IMAGES or parser_name in ("tesseract", "paddleocr")) else "pending",
    )

    # 扫描型 PDF / 图片 OCR 失败时提取不到文字，必须标记原因进入人工复核，
    # 不得以正常已解析状态静默入库。
    if not cleaned:
        reason = "empty_pdf: no extractable text" if suffix == ".pdf" else "empty_ocr: no extractable text"
        record.review_status = "needs_review"
        record.notes = (record.notes or "") + f"\n{reason}"

    phone_recovery: "RecoveryResult | None" = None
    source_is_visual = suffix in SUPPORTED_IMAGES or parser_name in ("tesseract", "paddleocr")
    if not record.phone and source_is_visual:
        from parsers.mosaic_phone_recovery import recover_phone

        recovered = recover_phone(path, parser_name, ocr_confidence)
        if recovered and recovered.phone:
            record.phone = recovered.phone
            record.review_status = "needs_review"
            record.notes = (record.notes or "") + f"\nPhone recovered via {recovered.source}."
            phone_recovery = recovered

    return _post_process_record(record, name_confidence, ocr_confidence, exp_confidence, phone_recovery)


def parse_resume_text(text: str, title: str = "", source_url: str = "", source_type: str = "manual_text") -> CandidateRecord:
    """Parse raw resume text (e.g. from browser extension) into a CandidateRecord."""
    cleaned = _clean_text(text)
    name = _extract_name(cleaned, title)
    name_confidence = 0.0
    if name:
        name_confidence = 1.0 if title and name in title else 0.9
    work_experiences, exp_confidence = _extract_experiences(cleaned)
    labeled_company, labeled_title = _extract_labeled_current_work(cleaned)

    record = CandidateRecord(
        name=name,
        phone=PHONE_RE.search(cleaned).group(0) if PHONE_RE.search(cleaned) else None,
        email=EMAIL_RE.search(cleaned).group(0) if EMAIL_RE.search(cleaned) else None,
        current_company=labeled_company,
        current_title=labeled_title,
        current_location=_infer_location(cleaned),
        employment_status=_infer_employment_status(cleaned),
        expected_salary=_infer_salary(cleaned),
        expected_location=_infer_expected_location(cleaned),
        skills=_infer_skills(cleaned),
        tech_stack=_infer_skills(cleaned),
        work_experiences=work_experiences,
        education=_extract_education(cleaned),
        raw_text=cleaned,
        source_url=source_url or None,
        source_type=source_type,
        source_platform=source_type,
        parser_name="regex_text",
        parser_version="0.1.0",
    )

    return _post_process_record(record, name_confidence, 1.0, exp_confidence)
