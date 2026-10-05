import re
from datetime import datetime
from typing import Dict, List


class OutputSafetyEngine:
    """Universal output safety checks for all agent responses."""

    _BLOCK_PATTERNS = [
        r"\bhow to (build|make|create).*(bomb|explosive)\b",
        r"\bcredit card (cvv|dump|clone)\b",
        r"\bkill (yourself|myself|himself|herself|themself)\b",
        r"\bchild sexual\b",
    ]
    _HALLUCINATION_MARKERS = [
        r"\bguaranteed\b",
        r"\b100%\s*(accurate|certain|sure)\b",
        r"\bi (already )?(sent|emailed|executed|ran)\b",
        r"\bwithout any doubt\b",
        r"\blorem ipsum\b",
        r"\btbd\b",
    ]

    @classmethod
    def _extract_dates(cls, text: str) -> List[str]:
        raw = text or ""
        found = set(re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", raw))
        for day, month, year in re.findall(
            r"\b(\d{1,2})\s+"
            r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+"
            r"(20\d{2})\b",
            raw,
            flags=re.IGNORECASE,
        ):
            try:
                dt = datetime.strptime(f"{day} {month} {year}", "%d %B %Y").strftime("%Y-%m-%d")
                found.add(dt)
            except Exception:
                pass
        return sorted(found)

    @classmethod
    def _extract_budget_max(cls, query: str) -> float:
        q = (query or "").lower()
        matches = re.findall(r"(?:under|below|upto|up to|max|maximum)\s+(?:rs\.?|inr|\$)?\s*(\d+(?:[.,]\d+)*)", q)
        if not matches:
            return -1.0
        vals = [float(m.replace(",", "")) for m in matches]
        return min(vals) if vals else -1.0

    @classmethod
    def _extract_prices(cls, text: str) -> List[float]:
        raw = (text or "").lower()
        out = []
        for p in re.findall(r"(?:₹|rs\.?|inr)\s*(\d[\d,]*)", raw):
            try:
                out.append(float(p.replace(",", "")))
            except Exception:
                pass
        return out

    @classmethod
    def _grounding_score(cls, output: str, context: str) -> float:
        out_tokens = set(re.findall(r"[a-zA-Z]{4,}", (output or "").lower()))
        ctx_tokens = set(re.findall(r"[a-zA-Z]{4,}", (context or "").lower()))
        if not out_tokens:
            return 1.0
        overlap = len(out_tokens & ctx_tokens) / max(1, len(out_tokens))
        return round(overlap, 3)

    @classmethod
    def evaluate(cls, query: str, output: str, grounding_context: str) -> Dict[str, object]:
        text = output or ""
        lower = text.lower()
        findings: List[str] = []

        if any(re.search(p, lower, flags=re.IGNORECASE) for p in cls._BLOCK_PATTERNS):
            return {
                "blocked": True,
                "reason": "Output blocked by content moderation policy.",
                "findings": ["content_moderation_block"],
            }

        if any(re.search(p, lower, flags=re.IGNORECASE) for p in cls._HALLUCINATION_MARKERS):
            findings.append("hallucination_marker_detected")

        requested_dates = cls._extract_dates(query)
        output_dates = cls._extract_dates(text)
        if len(requested_dates) >= 2 and output_dates:
            if requested_dates[0] not in output_dates or requested_dates[1] not in output_dates:
                findings.append("date_grounding_mismatch")

        budget_max = cls._extract_budget_max(query)
        prices = cls._extract_prices(text)
        if budget_max > 0 and prices:
            if min(prices) > budget_max:
                findings.append("budget_constraint_mismatch")

        grounding = cls._grounding_score(text, grounding_context)
        # Keep low-grounding as a signal, but avoid over-blocking otherwise useful outputs.
        if grounding < 0.05 and len(text) > 350:
            findings.append("low_grounding_score")

        # Treat lexical grounding as advisory unless accompanied by stronger hallucination markers.
        high_risk = any(f in findings for f in ["hallucination_marker_detected"])
        return {
            "blocked": False,
            "reason": "",
            "findings": findings[:8],
            "grounding_score": grounding,
            "high_risk": high_risk,
        }

    @classmethod
    def format_output(cls, text: str) -> str:
        output = (text or "").replace("\r\n", "\n")
        output = re.sub(r"[ \t]+\n", "\n", output)
        output = re.sub(r"\n{3,}", "\n\n", output).strip()

        # Keep table rows structurally safe.
        fixed_lines = []
        for line in output.split("\n"):
            stripped = line.strip()
            if stripped.startswith("|") and not stripped.endswith("|"):
                line = line.rstrip() + " |"
            fixed_lines.append(line)
        return "\n".join(fixed_lines).strip()
