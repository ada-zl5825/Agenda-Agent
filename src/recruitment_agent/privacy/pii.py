"""Deterministic redaction of unnecessary personal identifiers."""

import re
from collections.abc import Callable


class PiiRedactor:
    """Redact high-confidence PII patterns while retaining recruitment semantics."""

    _EMAIL = re.compile(r"(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
    _CHINA_ID = re.compile(r"(?<!\d)(?:\d{17}[\dXx]|\d{15})(?!\d)")
    _LABELED_PASSPORT = re.compile(
        r"(?i)(?P<label>(?:passport(?:\s*(?:no|number|id))?|护照(?:号|号码)?))"
        r"(?P<separator>\s*[:\uff1a#]?\s*)[A-Z0-9]{6,12}"
    )
    _LABELED_STUDENT_ID = re.compile(
        r"(?i)(?P<label>(?:student\s*(?:id|number)|学号))"
        r"(?P<separator>\s*[:\uff1a#]?\s*)[A-Z0-9-]{4,24}"
    )
    _LABELED_CANDIDATE_ID = re.compile(
        r"(?i)(?P<label>(?:candidate\s*(?:id|number)|application\s*(?:id|number)|"
        r"候选人(?:编号|号码|ID)|申请(?:编号|号码|ID)|应聘(?:编号|号码|ID)))"
        r"(?P<separator>\s*[:\uff1a#]?\s*)[A-Z0-9-]{4,40}"
    )
    _PHONE_CANDIDATE = re.compile(r"(?<![\w])(?:\+?\d[\d ()-]{5,}\d)(?![\w])")

    def redact(self, text: str) -> tuple[str, dict[str, int]]:
        counts: dict[str, int] = {}
        redacted = text
        redacted = self._replace(redacted, self._EMAIL, "[EMAIL_REDACTED]", "email", counts)
        redacted = self._replace(
            redacted,
            self._CHINA_ID,
            "[GOVERNMENT_ID_REDACTED]",
            "government_id",
            counts,
        )
        redacted = self._replace_labeled(
            redacted,
            self._LABELED_PASSPORT,
            "[GOVERNMENT_ID_REDACTED]",
            "passport",
            counts,
        )
        redacted = self._replace_labeled(
            redacted,
            self._LABELED_STUDENT_ID,
            "[STUDENT_ID_REDACTED]",
            "student_id",
            counts,
        )
        redacted = self._replace_labeled(
            redacted,
            self._LABELED_CANDIDATE_ID,
            "[CANDIDATE_ID_REDACTED]",
            "candidate_id",
            counts,
        )
        redacted = self._PHONE_CANDIDATE.sub(
            self._phone_replacement(counts),
            redacted,
        )
        return redacted, counts

    @staticmethod
    def _replace(
        text: str,
        pattern: re.Pattern[str],
        replacement: str,
        count_key: str,
        counts: dict[str, int],
    ) -> str:
        result, count = pattern.subn(replacement, text)
        if count:
            counts[count_key] = count
        return result

    @staticmethod
    def _replace_labeled(
        text: str,
        pattern: re.Pattern[str],
        replacement: str,
        count_key: str,
        counts: dict[str, int],
    ) -> str:
        def replace(match: re.Match[str]) -> str:
            return f"{match.group('label')}{match.group('separator')}{replacement}"

        result, count = pattern.subn(replace, text)
        if count:
            counts[count_key] = count
        return result

    @classmethod
    def _phone_replacement(cls, counts: dict[str, int]) -> Callable[[re.Match[str]], str]:
        def replace(match: re.Match[str]) -> str:
            candidate = match.group(0)
            digits = re.sub(r"\D", "", candidate)
            if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2})?", candidate.strip()):
                return candidate
            if re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", candidate.strip()):
                return candidate
            if re.fullmatch(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", candidate.strip()):
                return candidate
            if candidate.strip().isdigit() and len(digits) < 10:
                return candidate
            if 7 <= len(digits) <= 15:
                counts["phone"] = counts.get("phone", 0) + 1
                return "[PHONE_REDACTED]"
            return match.group(0)

        return replace
