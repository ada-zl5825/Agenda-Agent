"""High-recall, deterministic recruitment email prefilter."""

import re
from typing import ClassVar

from recruitment_agent.email.models import NormalizedEmail, PrefilterDecision, PrefilterResult


class RecruitmentPrefilter:
    """Conservatively reject only clear non-recruitment messages."""

    _RECRUITMENT_TERMS: ClassVar[dict[str, re.Pattern[str]]] = {
        "assessment": re.compile(
            r"(?:测评|笔试|在线测试|coding (?:test|challenge)|assessment)",
            re.I,
        ),
        "interview": re.compile(r"(?:面试|面谈|interview)", re.I),
        "recruitment": re.compile(r"(?:校招|招聘|应聘|候选人|recruit(?:ment|er)|candidate)", re.I),
        "application": re.compile(
            r"(?:职位申请|申请进度|application (?:received|status|update)|job application)",
            re.I,
        ),
        "offer_result": re.compile(r"(?:录用|offer|rejection|未通过|淘汰|招聘结果)", re.I),
        "deadline_action": re.compile(
            r"(?:截止|请.{0,8}(?:确认|完成|选择)|deadline|action required|confirm availability)",
            re.I,
        ),
        "role": re.compile(
            r"(?:工程师|开发岗|实习生|graduate (?:role|programme)|internship)",
            re.I,
        ),
    }
    _RECRUITMENT_DOMAIN = re.compile(
        r"(?:^|\.)(?:greenhouse\.io|lever\.co|myworkdayjobs\.com|workday\.com|"
        r"smartrecruiters\.com|ashbyhq\.com|successfactors\.(?:com|eu)|"
        r"jobs?\.|careers?\.)",
        re.I,
    )
    _UNLIKELY_SUBJECT = re.compile(
        r"(?:验证码|账单|付款成功|快递|外卖|促销|newsletter|receipt|invoice|"
        r"security alert|one[- ]time (?:code|password)|password reset|delivery update)",
        re.I,
    )

    def classify(self, email: NormalizedEmail, *, sanitized_body: str) -> PrefilterResult:
        searchable = f"{email.subject}\n{sanitized_body}"
        matched = tuple(
            rule_name
            for rule_name, pattern in self._RECRUITMENT_TERMS.items()
            if pattern.search(searchable)
        )
        if matched:
            return PrefilterResult(
                decision=PrefilterDecision.LIKELY_RECRUITMENT,
                matched_rules=matched,
            )

        domains = tuple(
            domain for domain in (email.sender_domain, email.outer_sender_domain) if domain
        )
        if any(self._RECRUITMENT_DOMAIN.search(domain) for domain in domains):
            return PrefilterResult(
                decision=PrefilterDecision.LIKELY_RECRUITMENT,
                matched_rules=("recruitment_sender_domain",),
            )

        if self._UNLIKELY_SUBJECT.search(email.subject):
            return PrefilterResult(
                decision=PrefilterDecision.UNLIKELY,
                matched_rules=("clear_non_recruitment_subject",),
            )
        return PrefilterResult(decision=PrefilterDecision.UNKNOWN, matched_rules=())
