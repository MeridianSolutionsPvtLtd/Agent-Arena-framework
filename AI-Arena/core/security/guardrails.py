import re
from contextvars import ContextVar, Token
from typing import Dict, List, Tuple


class GuardrailEngine:
    """Centralized sanitization, prompt-injection detection, and PII masking."""

    _PROMPT_INJECTION_PATTERNS = [
        r"\bignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)\b",
        r"\bdisregard\s+(all\s+)?(instructions?|rules|system)\b",
        r"\b(reveal|show|print|dump)\s+(the\s+)?(system|developer)\s+(prompt|message|instructions?)\b",
        r"\b(jailbreak|dan mode|do anything now)\b",
        r"\bpretend\s+to\s+be\s+(system|developer)\b",
        r"\boverride\s+(safety|guardrails?|policy)\b",
        r"\btool\s*:\s*(shell|python|execute)\b.*\b(ignore|bypass)\b",
    ]

    _EMAIL_PATTERN = (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]")
    _PHONE_PATTERN = re.compile(r"\b(?:\+\d{1,3}[-\s]?)?\(?\d{3}\)?[-\s]?\d{3}[-\s]?\d{4}\b|\b\d{10}\b")
    _PII_PATTERNS = [
        (_PHONE_PATTERN, "[REDACTED_PHONE]"),
        (re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"), "[REDACTED_AADHAAR]"),
        (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[REDACTED_PAN]"),
        (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[REDACTED_CARD]"),
        (re.compile(r"\b(?:sk|pk|rk|api|token|key)[-_]?[A-Za-z0-9]{12,}\b", re.IGNORECASE), "[REDACTED_SECRET]"),
        (re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\b"), "[REDACTED_JWT]"),
        (re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}\b", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
    ]
    _PII_CONTEXT: ContextVar[Dict[str, str]] = ContextVar("pii_context", default={})

    @classmethod
    def sanitize_text(cls, text: str, max_len: int = 8000) -> str:
        raw = (text or "")
        cleaned = raw.replace("\x00", " ")
        cleaned = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", " ", cleaned)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
        return cleaned[:max_len]

    @classmethod
    def analyze_prompt_injection(cls, text: str) -> Dict[str, object]:
        lowered = (text or "").lower()
        matches: List[str] = []
        for pattern in cls._PROMPT_INJECTION_PATTERNS:
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                matches.append(pattern)
        return {
            "is_suspicious": bool(matches),
            "severity": "high" if len(matches) >= 2 else ("medium" if len(matches) == 1 else "none"),
            "matches": matches[:5],
        }

    @classmethod
    def mask_pii(cls, text: str, mask_email: bool = True) -> str:
        masked = text or ""
        if mask_email:
            masked = cls._EMAIL_PATTERN[0].sub(cls._EMAIL_PATTERN[1], masked)
        for pattern, replacement in cls._PII_PATTERNS:
            masked = pattern.sub(replacement, masked)
        return masked

    @classmethod
    def tokenize_pii(cls, text: str, tokenize_email: bool = True) -> Tuple[str, Dict[str, str]]:
        source = text or ""
        mapping: Dict[str, str] = {}
        counters = {"EMAIL": 0, "PHONE": 0, "ACCOUNT": 0}

        def _replace(pattern: re.Pattern, prefix: str, working: str) -> str:
            def repl(match):
                raw = match.group(0)
                for token, value in mapping.items():
                    if value == raw:
                        return token
                counters[prefix] += 1
                token = f"<PII_{prefix}_{counters[prefix]}>"
                mapping[token] = raw
                return token
            return pattern.sub(repl, working)

        tokenized = source
        if tokenize_email:
            tokenized = _replace(cls._EMAIL_PATTERN[0], "EMAIL", tokenized)
        tokenized = _replace(cls._PHONE_PATTERN, "PHONE", tokenized)
        return tokenized, mapping

    @classmethod
    def detokenize_text(cls, text: str, pii_map: Dict[str, str]) -> str:
        out = text or ""
        for token, raw in (pii_map or {}).items():
            out = out.replace(token, raw)
        return out

    @classmethod
    def set_runtime_pii_map(cls, pii_map: Dict[str, str]) -> Token:
        return cls._PII_CONTEXT.set(dict(pii_map or {}))

    @classmethod
    def reset_runtime_pii_map(cls, token: Token) -> None:
        cls._PII_CONTEXT.reset(token)

    @classmethod
    def resolve_runtime_pii(cls, text: str) -> str:
        return cls.detokenize_text(text, cls._PII_CONTEXT.get() or {})
