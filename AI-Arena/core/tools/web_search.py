from typing import Any, Dict, List, Type
import urllib.request
import urllib.parse
import json
import logging
import warnings
import re
import os
import ipaddress
import socket
from datetime import datetime
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from dotenv import load_dotenv

try:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*duckduckgo_search.*renamed to ddgs.*")
        from ddgs import DDGS
except ImportError:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*duckduckgo_search.*renamed to ddgs.*")
        from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)
load_dotenv()


def _is_safe_public_url(url: str) -> bool:
    """Reject local/private network targets before server-side HTTP requests."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            return False
        for result in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM):
            address = ipaddress.ip_address(result[4][0])
            if (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_reserved
                or address.is_unspecified
            ):
                return False
        return True
    except (OSError, ValueError):
        return False


class WebSearchInput(BaseModel):
    """Input schema for web_search."""

    query: str = Field(default="", description="The search query (used in search mode).")
    action: str = Field(default="search", description="Either 'search' or 'scrape'.")
    target_url: str = Field(default="", description="The URL to scrape (used in scrape mode).")
    region: str = Field(default="in-en", description="Search region (default 'in-en').")
    max_results: int = Field(default=8, description="Number of results to fetch (default 8).")
    checkin: str = Field(default="", description="Check-in date (YYYY-MM-DD).")
    checkout: str = Field(default="", description="Check-out date (YYYY-MM-DD).")
    strict_mode: bool = Field(default=True, description="Enable constraint-aware scoring and filtering.")
    evidence_depth: int = Field(default=3, description="How many top links to scrape for stronger evidence.")


class WebSearchTool(BaseTool):
    name: str = "web_search"
    description: str = (
        "A dual-mode tool for high-fidelity web research and scraping."
        "\n\nMODE 1: 'search' (default)"
        "\n- Use this to find information, links, and summaries from the web."
        "\n- Supports strict constraint scoring for hotel/travel queries (checkin, checkout, adults)."
        "\n\nMODE 2: 'scrape'"
        "\n- Use this when you have a specific 'target_url' and need to read the full page content."
        "\n\nRULES:"
        "\n- For search, the tool applies a 'fidelity' score. High score means results perfectly match your query constraints."
        "\n- Scrape is limited to ~8000 characters to prevent context overflow."
    )
    args_schema: Type[BaseModel] = WebSearchInput

    def _apply_generic_filters(self, url: str, filters: Dict[str, Any]) -> str:
        try:
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            if filters.get("checkin"):
                params["checkin"] = [filters["checkin"]]
                params["startDate"] = [filters["checkin"]]
            if filters.get("checkout"):
                params["checkout"] = [filters["checkout"]]
                params["endDate"] = [filters["checkout"]]
            if filters.get("adults"):
                params["adults"] = [str(filters["adults"])]
            rebuilt = parsed._replace(query=urllib.parse.urlencode(params, doseq=True))
            return urllib.parse.urlunparse(rebuilt)
        except Exception:
            return url

    def _apply_domain_adapter(self, url: str, filters: Dict[str, Any]) -> str:
        checkin = filters.get("checkin", "")
        checkout = filters.get("checkout", "")
        if not checkin or not checkout:
            return url
        try:
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            adults_val = str(max(1, int(filters.get("adults", 2))))
            host = (parsed.netloc or "").lower()

            if "booking.com" in host:
                params["checkin"] = [checkin]
                params["checkout"] = [checkout]
                params["group_adults"] = [adults_val]
                params["no_rooms"] = ["1"]
                params["group_children"] = ["0"]
            elif "expedia" in host:
                params["checkIn"] = [checkin]
                params["checkOut"] = [checkout]
                params["adults"] = [adults_val]
            elif "goibibo" in host:
                d, m, y = checkin.split("-")
                params["checkin"] = [f"{d}{m}{y}"]
                params["checkout"] = [checkout.replace("-", "")]
                params["rooms"] = [f"1-0-{adults_val}"]
            elif "makemytrip" in host:
                params["checkin"] = [checkin.replace("-", "")]
                params["checkout"] = [checkout.replace("-", "")]
                params["roomStayQualifier"] = ["2e0e"]
            else:
                return url

            rebuilt = parsed._replace(query=urllib.parse.urlencode(params, doseq=True))
            return urllib.parse.urlunparse(rebuilt)
        except Exception:
            return url

    def _apply_filter_adapters(self, url: str, filters: Dict[str, Any], force: bool = False) -> str:
        # Keep search generic by default; allow forced hardening for hotel-intent flows.
        if not force and os.getenv("ENABLE_FILTER_URL_HINTS", "false").lower() != "true":
            return url
        hardened = self._apply_generic_filters(url, filters)
        if os.getenv("ENABLE_DOMAIN_LINK_ADAPTERS", "false").lower() == "true":
            hardened = self._apply_domain_adapter(hardened, filters)
        return hardened

    def _extract_dates_from_text(self, text: str) -> List[str]:
        raw = (text or "")
        found = set()
        for d in re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", raw):
            found.add(d)
        for y, m, d in re.findall(r"\b(20\d{2})(\d{2})(\d{2})\b", raw):
            try:
                found.add(datetime(int(y), int(m), int(d)).strftime("%Y-%m-%d"))
            except Exception:
                pass
        return sorted(found)

    def _filter_capability_score(self, url: str, filters: Dict[str, Any], evidence_text: str = "") -> Dict[str, Any]:
        requested, matched, missing = [], [], []
        checkin = filters.get("checkin", "")
        checkout = filters.get("checkout", "")
        adults = str(filters.get("adults", "")) if filters.get("adults") else ""
        price_min = filters.get("price_min")
        price_max = filters.get("price_max")

        url_lower = (url or "").lower()
        evidence_lower = (evidence_text or "").lower()

        url_dates = set(self._extract_dates_from_text(url))
        evidence_dates = set(self._extract_dates_from_text(evidence_text))
        observed_dates = set(url_dates | evidence_dates)
        date_mismatch = False

        if checkin:
            requested.append("checkin")
            if checkin in observed_dates:
                matched.append("checkin")
            else:
                missing.append("checkin")
        if checkout:
            requested.append("checkout")
            if checkout in observed_dates:
                matched.append("checkout")
            else:
                missing.append("checkout")

        if checkin and checkout:
            if evidence_dates:
                if checkin not in evidence_dates or checkout not in evidence_dates:
                    date_mismatch = True
            elif observed_dates:
                if checkin not in observed_dates or checkout not in observed_dates:
                    date_mismatch = True

        if adults:
            requested.append("adults")
            adults_present = (
                f"adults={adults}" in url_lower
                or f"adult={adults}" in url_lower
                or f"adults {adults}" in evidence_lower
                or f"{adults} adult" in evidence_lower
                or f"{adults} adults" in evidence_lower
            )
            if adults_present:
                matched.append("adults")
            else:
                missing.append("adults")

        if price_min is not None or price_max is not None:
            requested.append("price")
            has_currency = any(tok in evidence_lower for tok in ["₹", "rs", "inr", "$"])
            has_numbers = bool(re.search(r"\d{3,}", evidence_lower))
            if has_currency or has_numbers:
                matched.append("price")
            else:
                missing.append("price")

        if not requested:
            return {"fidelity": "not_requested", "score": 1.0, "matched": [], "missing": [], "date_mismatch": False}

        score = round(len(matched) / max(1, len(requested)), 3)
        if date_mismatch:
            score = min(score, 0.2)
            missing.append("date_exact_match")
            fidelity = "low"
        elif score >= 0.8:
            fidelity = "high"
        elif score >= 0.4:
            fidelity = "medium"
        else:
            fidelity = "low"

        return {
            "fidelity": fidelity,
            "score": score,
            "matched": matched,
            "missing": missing,
            "date_mismatch": date_mismatch,
            "observed_dates": sorted(observed_dates)[:8],
            "evidence_dates": sorted(evidence_dates)[:8],
        }

    def _infer_dates_from_query(self, query: str) -> Dict[str, str]:
        q = (query or "").lower()
        now = datetime.now()
        months = {
            "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
            "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        }
        iso_dates = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", q)
        if len(iso_dates) >= 2:
            return {"checkin": iso_dates[0], "checkout": iso_dates[1]}

        range_match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(?:to|-)\s*(\d{1,2})(?:st|nd|rd|th)?\b", q)
        if range_match:
            day1, day2 = int(range_match.group(1)), int(range_match.group(2))
            month, year = now.month, now.year
            if "next month" in q:
                month = 1 if now.month == 12 else now.month + 1
                year = now.year + 1 if now.month == 12 else now.year
            elif "this month" not in q:
                for m_name, m_num in months.items():
                    if m_name in q:
                        month = m_num
                        break
            try:
                return {
                    "checkin": datetime(year, month, day1).strftime("%Y-%m-%d"),
                    "checkout": datetime(year, month, day2).strftime("%Y-%m-%d"),
                }
            except Exception:
                pass

        month_day_match = re.search(
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+"
            r"(\d{1,2})(?:st|nd|rd|th)?\s*(?:to|-)\s*"
            r"(?:(january|february|march|april|may|june|july|august|september|october|november|december)\s+)?"
            r"(\d{1,2})(?:st|nd|rd|th)?\s*(20\d{2})?",
            q,
        )
        if month_day_match:
            m1 = month_day_match.group(1)
            d1 = int(month_day_match.group(2))
            m2 = month_day_match.group(3) or m1
            d2 = int(month_day_match.group(4))
            y = int(month_day_match.group(5)) if month_day_match.group(5) else now.year
            try:
                return {
                    "checkin": datetime(y, months[m1], d1).strftime("%Y-%m-%d"),
                    "checkout": datetime(y, months[m2], d2).strftime("%Y-%m-%d"),
                }
            except Exception:
                pass
        return {"checkin": "", "checkout": ""}

    def _infer_adults_from_query(self, query: str) -> int:
        q = (query or "").lower()
        match = re.search(r"\b(\d{1,2})\s*(?:people|persons|person|adults|adult|guests|guest)\b", q)
        if match:
            return max(1, int(match.group(1)))
        return 2 if "couple" in q else 2

    def _quick_scrape(self, url: str, max_chars: int = 4000) -> str:
        try:
            if not _is_safe_public_url(url):
                logger.warning("Blocked unsafe web scrape target")
                return ""
            req = urllib.request.Request(
                url,
                data=None,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                },
            )
            response = urllib.request.urlopen(req, timeout=8)
            if not _is_safe_public_url(response.geturl()):
                response.close()
                logger.warning("Blocked unsafe web scrape redirect")
                return ""
            html = response.read().decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html, "html.parser")
            for script in soup(["script", "style"]):
                script.extract()
            return soup.get_text(separator=" ", strip=True)[:max_chars]
        except Exception:
            return ""

    def _extract_constraints(self, query: str) -> Dict[str, Any]:
        q = (query or "").strip()
        q_lower = q.lower()
        required_phrases = [a or b for a, b in re.findall(r'"([^"]+)"|\'([^\']+)\'', q) if (a or b)]

        excluded_phrases: List[str] = []
        for pat in [r"without\s+([a-z0-9\-\s]{2,40})", r"exclude\s+([a-z0-9\-\s]{2,40})", r"avoid\s+([a-z0-9\-\s]{2,40})"]:
            excluded_phrases.extend([m.strip() for m in re.findall(pat, q_lower)])

        numeric_rules: List[Dict[str, Any]] = []
        for m in re.findall(r"(under|below|less than)\s+\$?(\d+(?:[.,]\d+)*)", q_lower):
            numeric_rules.append({"op": "max", "value": float(m[1].replace(",", "")), "raw": " ".join(m)})
        for m in re.findall(r"(upto|up to|max|maximum)\s+(?:rs\.?|inr|\$)?\s*(\d+(?:[.,]\d+)*)", q_lower):
            numeric_rules.append({"op": "max", "value": float(m[1].replace(",", "")), "raw": " ".join(m)})
        for m in re.findall(r"(over|above|more than|at least)\s+\$?(\d+(?:[.,]\d+)*)", q_lower):
            numeric_rules.append({"op": "min", "value": float(m[1].replace(",", "")), "raw": " ".join(m)})
        for low, high in re.findall(r"between\s+\$?(\d+(?:[.,]\d+)*)\s+and\s+\$?(\d+(?:[.,]\d+)*)", q_lower):
            numeric_rules.append({"op": "range", "min": float(low.replace(",", "")), "max": float(high.replace(",", "")), "raw": f"between {low} and {high}"})
        for low, high in re.findall(r"from\s+(?:rs\.?|inr|\$)?\s*(\d+(?:[.,]\d+)*)\s+to\s+(?:rs\.?|inr|\$)?\s*(\d+(?:[.,]\d+)*)", q_lower):
            numeric_rules.append({"op": "range", "min": float(low.replace(",", "")), "max": float(high.replace(",", "")), "raw": f"from {low} to {high}"})

        stop = {
            "find", "search", "look", "for", "the", "a", "an", "with", "and", "or", "best", "top", "latest",
            "from", "to", "in", "on", "at", "of", "by", "please", "show", "give", "me", "results",
            "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
            "checkin", "checkout", "budget", "night", "person", "people", "adult", "adults", "guest", "guests", "stay",
        }
        tokens = [t for t in re.findall(r"[a-z]{3,}", q_lower) if t not in stop]
        seen, core_terms = set(), []
        for t in tokens:
            if t in seen:
                continue
            seen.add(t)
            core_terms.append(t)
        core_terms = core_terms[:8]
        return {
            "required_phrases": required_phrases,
            "excluded_phrases": excluded_phrases[:6],
            "numeric_rules": numeric_rules[:6],
            "core_terms": core_terms,
        }

    def _evaluate_constraints(self, text: str, constraints: Dict[str, Any]) -> Dict[str, Any]:
        text_lower = (text or "").lower()
        matched: List[str] = []
        violations: List[str] = []
        score, possible = 0.0, 0.0

        for phrase in constraints.get("required_phrases", []):
            possible += 1.0
            if phrase.lower() in text_lower:
                score += 1.0
                matched.append(f"required:{phrase}")
            else:
                violations.append(f"missing_required:{phrase}")

        for phrase in constraints.get("excluded_phrases", []):
            possible += 1.0
            if phrase.lower() in text_lower:
                violations.append(f"excluded_present:{phrase}")
            else:
                score += 1.0
                matched.append(f"excluded_ok:{phrase}")

        numbers_in_text = [float(n.replace(",", "")) for n in re.findall(r"\$?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)", text_lower)]
        for rule in constraints.get("numeric_rules", []):
            possible += 1.0
            if not numbers_in_text:
                violations.append(f"no_numeric_evidence:{rule.get('raw', '')}")
                continue
            if rule["op"] == "max":
                if min(numbers_in_text) <= rule["value"]:
                    score += 1.0
                    matched.append(f"numeric_max_ok:{rule['value']}")
                else:
                    violations.append(f"numeric_max_violation:{rule['value']}")
            elif rule["op"] == "min":
                if max(numbers_in_text) >= rule["value"]:
                    score += 1.0
                    matched.append(f"numeric_min_ok:{rule['value']}")
                else:
                    violations.append(f"numeric_min_violation:{rule['value']}")
            elif rule["op"] == "range":
                in_range = [n for n in numbers_in_text if rule["min"] <= n <= rule["max"]]
                if in_range:
                    score += 1.0
                    matched.append(f"numeric_range_ok:{rule['min']}-{rule['max']}")
                else:
                    violations.append(f"numeric_range_violation:{rule['min']}-{rule['max']}")

        core_terms = constraints.get("core_terms", [])
        if core_terms:
            possible += min(3.0, float(len(core_terms)))
            covered = sum(1 for t in core_terms if t in text_lower)
            score += min(3.0, float(covered))
            if covered:
                matched.append(f"core_terms:{covered}/{len(core_terms)}")
            if covered == 0:
                violations.append("core_terms_zero_match")
            elif covered == 1 and len(core_terms) >= 3:
                violations.append("core_terms_weak_match")

        confidence = round((score / possible), 3) if possible > 0 else 0.5
        hard_fail = any(v.startswith("missing_required") or v.startswith("excluded_present") or v == "core_terms_zero_match" for v in violations)
        return {"confidence": confidence, "hard_fail": hard_fail, "matched": matched[:8], "violations": violations[:8]}

    def _serpapi_search(
        self,
        query: str,
        region: str,
        max_results: int,
        checkin: str = "",
        checkout: str = "",
        adults: int = 2,
    ) -> List[Dict[str, Any]]:
        api_key = (
            os.getenv("SERPAPI_API_KEY", "").strip()
            or os.getenv("SERP_API_KEY", "").strip()
            or os.getenv("SERPAPI_KEY", "").strip()
        )
        if not api_key:
            raise ValueError("SerpAPI key is not configured. Set SERPAPI_API_KEY in .env.")

        gl = "in" if region.startswith("in") else "us"
        hl = "en"
        is_hotel_query = any(k in (query or "").lower() for k in ["hotel", "hotels", "stay", "resort", "hostel", "room"])

        def _fetch(params: Dict[str, Any]) -> Dict[str, Any]:
            url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            response = urllib.request.urlopen(req, timeout=25)
            return json.loads(response.read().decode("utf-8", errors="ignore"))

        normalized: List[Dict[str, Any]] = []
        if is_hotel_query and checkin and checkout:
            hotel_params = {
                "engine": "google_hotels",
                "q": query,
                "gl": gl,
                "hl": hl,
                "check_in_date": checkin,
                "check_out_date": checkout,
                "adults": max(1, int(adults or 2)),
                "currency": "INR",
                "api_key": api_key,
            }
            hotel_payload = _fetch(hotel_params)
            hotel_rows = (
                hotel_payload.get("properties")
                or hotel_payload.get("hotel_results")
                or hotel_payload.get("hotels")
                or []
            )
            for item in hotel_rows[: max(1, min(max_results, 20))]:
                title = item.get("name") or item.get("title") or "Untitled"
                link = item.get("link") or item.get("website") or item.get("url") or ""
                if not link:
                    gps = item.get("gps_coordinates") or {}
                    lat = gps.get("latitude")
                    lng = gps.get("longitude")
                    if lat is not None and lng is not None:
                        link = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
                total_rate = item.get("rate_per_night") or item.get("price") or item.get("total_rate") or ""
                rating = item.get("overall_rating") or item.get("rating") or ""
                snippet = f"checkin {checkin} checkout {checkout} adults {max(1, int(adults or 2))}"
                if total_rate:
                    snippet += f" | rate {total_rate}"
                if rating:
                    snippet += f" | rating {rating}"
                normalized.append({"title": title, "url": link, "snippet": snippet})

        if normalized:
            return normalized

        params = {
            "engine": "google",
            "q": query,
            "gl": gl,
            "hl": hl,
            "num": max(1, min(max_results, 20)),
            "api_key": api_key,
        }
        payload = _fetch(params)
        organic = payload.get("organic_results", []) or []
        for item in organic:
            link = item.get("link") or item.get("url") or ""
            if not link:
                continue
            normalized.append(
                {
                    "title": item.get("title") or "Untitled",
                    "url": link,
                    "snippet": item.get("snippet") or item.get("snippet_highlighted_words") or "",
                }
            )
        return normalized

    def _ddgs_search(self, query: str, region: str, max_results: int) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        with DDGS() as ddgs:
            raw_results = list(ddgs.text(query, region=region, max_results=max_results))
        for item in raw_results:
            link = item.get("href") or item.get("link") or ""
            if not link:
                continue
            normalized.append(
                {
                    "title": item.get("title") or "Untitled",
                    "url": link,
                    "snippet": item.get("body") or item.get("snippet") or "",
                }
            )
        return normalized

    def _resolve_provider(self) -> str:
        env_provider = os.getenv("WEB_SEARCH_PROVIDER", "").strip().lower()
        if env_provider == "serpapi":
            return env_provider
        return "ddgs"

    def _run(
        self,
        query: str = "",
        action: str = "search",
        target_url: str = "",
        region: str = "in-en",
        max_results: int = 8,
        checkin: str = "",
        checkout: str = "",
        strict_mode: bool = True,
        evidence_depth: int = 3,
    ) -> str:
        if action.lower() == "scrape":
            if not target_url:
                return "Error: action='scrape' requires a valid 'target_url'."
            return self._quick_scrape(target_url, max_chars=8000) or f"Failed to scrape {target_url}."

        try:
            if not query:
                return "Error: action='search' requires a valid 'query'."

            # ── Query Sanitization ──
            # Strip common agent filler phrases to improve search fidelity
            original_query = query
            query = re.sub(r'(?i)^(search the web for|search for|find|look for|get|retrieve|locate|identify)\s+', '', query)
            query = re.sub(r'(?i)\s+(for Alex|for student|in the assessment report|identified earlier|relevant to)$', '', query)
            query = query.strip()
            
            if len(query) < 2:
                query = original_query # Fallback if cleaning was too aggressive

            active_provider = self._resolve_provider()
            logger.info("Performing web search (%s) for query: %s", active_provider, query)

            safe_max = max(1, min(max_results, 20))
            inferred_dates = self._infer_dates_from_query(query)
            inferred_checkin = checkin or inferred_dates.get("checkin", "")
            inferred_checkout = checkout or inferred_dates.get("checkout", "")
            inferred_adults = self._infer_adults_from_query(query)
            inferred_filters = {
                "checkin": inferred_checkin,
                "checkout": inferred_checkout,
                "adults": inferred_adults,
            }
            
            # ── Education & Authority Boosting ──
            # Favor high-quality educational domains for tutorial-intent queries
            is_edu_query = any(
                kw in query.lower() for kw in ["tutorial", "learn", "lesson", "explain", "physics", "math", "science"]
            )
            if is_edu_query:
                # Light nudge — avoid stuffing brand names that confuse DDGS ranking for article-like missions
                if "physics" in query.lower() and not any(
                    x in query.lower() for x in ("site:", "khan", "hyperphysics", "britannica")
                ):
                    query = f"{query} physics explained article"
                logger.info("Education intent detected, light query boost applied.")

            is_hotel_query = any(
                kw in (query or "").lower()
                for kw in ["hotel", "hotels", "stay", "resort", "hostel", "room"]
            )

            # ── Video intent (narrow) ──
            # Do NOT treat the word "tutorial" alone as video intent — study plans often say "tutorial"
            # but users want articles + mixed web results. Only force YouTube when explicitly requested.
            ql = (query or "").lower()
            is_video_intent = (
                "youtube.com" in ql
                or "youtu.be" in ql
                or "site:youtube.com" in ql
                or "watch a video" in ql
                or "watch this video" in ql
                or "video only" in ql
                or re.search(r"\bvideo\s+tutorial\b", ql)
            )
            if is_video_intent:
                if "youtube.com" not in ql and "youtu.be" not in ql and "site:" not in ql:
                    query = f"site:youtube.com {query}"
                logger.info("Explicit video intent — restricting to YouTube.")

            if active_provider == "ddgs":
                raw_results = self._ddgs_search(query=query, region=region, max_results=safe_max)
            else:
                raw_results = self._serpapi_search(
                    query=query,
                    region=region,
                    max_results=safe_max,
                    checkin=inferred_checkin,
                    checkout=inferred_checkout,
                    adults=inferred_adults,
                )
            
            if not raw_results:
                return json.dumps({"query": query, "results": []})

            # Filter for direct video links if video intent is active
            if is_video_intent:
                video_results = [r for r in raw_results if "watch?v=" in r.get("url", "") or "youtu.be/" in r.get("url", "")]
                if video_results:
                    raw_results = video_results
                logger.info(f"Filtered to {len(raw_results)} direct video links.")

            normalized: List[Dict[str, Any]] = []
            for item in raw_results:
                force_harden = bool(is_hotel_query and inferred_checkin and inferred_checkout)
                hardened_url = self._apply_filter_adapters(item["url"], inferred_filters, force=force_harden)
                
                # ── YouTube URL Sanitization ──
                if "youtube.com" in hardened_url or "youtu.be" in hardened_url:
                    # Strip search-tracking parameters that might cause redirects to fail over time
                    hardened_url = re.sub(r'(\?|&)(?:utm_source|feature|app|search|s|q)=[^&]*', '', hardened_url).rstrip('?&')

                normalized.append(
                    {
                        "title": item["title"],
                        "url": hardened_url,
                        "snippet": item.get("snippet", ""),
                    }
                )

            if not strict_mode:
                return json.dumps({"query": query, "results": normalized}, indent=2)

            constraints = self._extract_constraints(query)
            inferred_price_min, inferred_price_max = None, None
            for rule in constraints.get("numeric_rules", []):
                if rule.get("op") == "range":
                    inferred_price_min, inferred_price_max = rule.get("min"), rule.get("max")
                    break
                if rule.get("op") == "max":
                    inferred_price_max = rule.get("value")
            inferred_filters["price_min"] = inferred_price_min
            inferred_filters["price_max"] = inferred_price_max
            
            depth = max(0, min(evidence_depth, len(normalized)))
            evaluated: List[Dict[str, Any]] = []
            for idx, result in enumerate(normalized):
                # Only scrape the configured evidence depth.  Scraping every
                # SERP hit makes the local summarizer slow and bloats context.
                if idx >= depth:
                    evaluated.append({**result, "verification_note": "not_scraped_evidence_depth"})
                    continue
                evidence = result["snippet"]
                # ALWAYS attempt to verify the link is alive and has content
                scraped = self._quick_scrape(result["url"])
                if not scraped or len(scraped) < 500:
                    logger.warning(f"Discarding low-fidelity or broken link: {result['url']}")
                    continue # SKIP broken or 'ghost' links
                
                evidence = f"{result['snippet']} {scraped}"
                capability = self._filter_capability_score(result["url"], inferred_filters, evidence)
                assessment = self._evaluate_constraints(evidence, constraints)
                enriched = {
                    **result,
                    "confidence_score": assessment["confidence"],
                    "matched_constraints": assessment["matched"],
                    "violations": assessment["violations"],
                    "hard_fail": assessment["hard_fail"],
                    "filter_fidelity": capability["fidelity"],
                    "filter_capability_score": capability["score"],
                    "matched_filter_fields": capability["matched"],
                    "missing_filter_fields": capability["missing"],
                    "observed_dates": capability.get("observed_dates", []),
                    "evidence_dates": capability.get("evidence_dates", []),
                    # Keep both a short preview for ranking/UI and bounded page
                    # content for the downstream local summarizer. Never return
                    # unbounded HTML or the full raw response.
                    "content_preview": scraped[:800],
                    "content": scraped[:8000],
                }
                if capability["fidelity"] == "low":
                    enriched["confidence_score"] = round(max(0.0, enriched["confidence_score"] - 0.2), 3)
                    enriched["violations"] = (enriched.get("violations") or []) + ["filter_fidelity_low:missing_requested_filters"]
                if capability.get("date_mismatch"):
                    enriched["hard_fail"] = True
                    enriched["violations"] = (enriched.get("violations") or []) + ["date_mismatch_detected"]
                evaluated.append(enriched)
            
            # If strict scrape/constraints dropped everything, still return raw search hits so callers get real URLs
            # (never empty JSON — downstream LLMs invent plausible Khan Academy / textbook URLs otherwise).
            if not evaluated and normalized:
                logger.warning(
                    "Strict scrape/constraints filtered all candidates; returning unverified search URLs only."
                )
                fallback_rows = [
                    {
                        "title": x.get("title") or "Untitled",
                        "url": x.get("url") or "",
                        "snippet": x.get("snippet") or "",
                        "verification_note": "unscraped_fallback",
                    }
                    for x in normalized[:safe_max]
                    if x.get("url")
                ]
                return json.dumps(
                    {
                        "query": query,
                        "provider": active_provider,
                        "strict_mode": True,
                        "verification_note": "Links are from the search provider but pages were not scraped (timeout, short body, or filters). URLs are still authentic SERP/DDGS hits.",
                        "results": fallback_rows,
                    },
                    indent=2,
                )

            evaluated.sort(key=lambda x: (x.get("hard_fail", False), -x.get("confidence_score", 0.0)))
            final_results = [r for r in evaluated if not r.get("hard_fail")] or evaluated
            for index, item in enumerate(final_results, start=1):
                preview = (item.get("content_preview") or item.get("snippet") or "").replace("\n", " ").strip()
                logger.info(
                    "[WebSearch] Result %d | title=%r | url=%s | snippet=%s | preview_chars=%d | content_chars=%d",
                    index,
                    (item.get("title") or "")[:160],
                    item.get("url") or "",
                    preview[:180],
                    len(item.get("content_preview") or item.get("snippet") or ""),
                    len(item.get("content") or ""),
                )
            if any(
                [
                    inferred_filters.get("checkin"),
                    inferred_filters.get("checkout"),
                    inferred_filters.get("adults"),
                    inferred_filters.get("price_min"),
                    inferred_filters.get("price_max"),
                ]
            ):
                final_results.sort(
                    key=lambda x: (
                        0 if x.get("filter_fidelity") == "high" else (1 if x.get("filter_fidelity") == "medium" else 2),
                        -x.get("confidence_score", 0.0),
                    )
                )

            return json.dumps(
                {
                    "query": query,
                    "provider": active_provider,
                    "applied_filters": {
                        "checkin": inferred_checkin,
                        "checkout": inferred_checkout,
                        "adults": inferred_adults,
                        "url_hardening_forced": bool(is_hotel_query and inferred_checkin and inferred_checkout),
                        "domain_adapters_enabled": os.getenv("ENABLE_DOMAIN_LINK_ADAPTERS", "false").lower() == "true",
                    },
                    "constraints": constraints,
                    "strict_mode": True,
                    "results": final_results,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"query": query, "provider": self._resolve_provider(), "results": [], "error": str(e)})


web_search = WebSearchTool()
