"""Turning evidence dates into a recency signal.

PRD principle #5 says recent developments should count for more. Until now
that existed only as a sentence in the scorer's prompt — and the prompt was
never given any dates, so the model was asked to weigh recency while being
told nothing about it.

This module answers two questions from the evidence itself:
  - how old is the freshest thing we found?
  - how much of what we found is recent, rather than one old article?

Both feed the score. A company whose only coverage is three years old is
genuinely less worth someone's time today, and the number should say so.
"""

import re
from dataclasses import dataclass
from datetime import date

# Bounded so recency adjusts a score rather than deciding it: the four
# dimensions remain the substance, this tilts the total.
MIN_FACTOR = 0.70
MAX_FACTOR = 1.05

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_date(value: str | None) -> date | None:
    """Parse the date formats that actually turn up in extracted evidence.

    Sources are inconsistent: "2026-03-14", "2026-03", "2026", "March 2026",
    "14 March 2026". Anything unrecognised is treated as undated rather than
    guessed at — a wrong date would quietly distort the score.
    """
    if not value or not isinstance(value, str):
        return None

    text = value.strip().lower()
    if not text or text in {"unknown", "none", "null", "n/a"}:
        return None

    # 2026-03-14 / 2026/03/14 / 2026-03 / 2026
    iso = re.match(r"^(\d{4})(?:[-/](\d{1,2}))?(?:[-/](\d{1,2}))?", text)
    if iso:
        year = int(iso.group(1))
        month = int(iso.group(2)) if iso.group(2) else 1
        day = int(iso.group(3)) if iso.group(3) else 1
        return _safe_date(year, month, day)

    # "march 2026" / "14 march 2026" / "mar 2026"
    named = re.search(r"([a-z]{3,})\s+(\d{4})", text)
    if named:
        month = _MONTHS.get(named.group(1)[:3])
        if month:
            day_match = re.match(r"^(\d{1,2})\s", text)
            day = int(day_match.group(1)) if day_match else 1
            return _safe_date(int(named.group(2)), month, day)

    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    # Extracted values can be malformed (month 13, day 32) or absurd years.
    if not (1900 <= year <= 2200):
        return None
    try:
        return date(year, min(max(month, 1), 12), min(max(day, 1), 28))
    except ValueError:
        return None


@dataclass
class RecencyProfile:
    newest: date | None = None
    months_since_newest: float | None = None
    dated_count: int = 0
    undated_count: int = 0
    within_6_months: int = 0
    within_12_months: int = 0
    within_24_months: int = 0

    @property
    def total(self) -> int:
        return self.dated_count + self.undated_count

    @property
    def recent_share(self) -> float:
        """Share of *dated* evidence from the last 12 months.

        Measured against dated evidence only: undated items are already
        penalised through the coverage factor, and counting them here would
        punish the same gap twice.
        """
        if self.dated_count == 0:
            return 0.0
        return self.within_12_months / self.dated_count


def build_profile(dates: list[str | None], today: date | None = None) -> RecencyProfile:
    today = today or date.today()
    profile = RecencyProfile()

    parsed: list[date] = []
    for raw in dates:
        d = parse_date(raw)
        if d is None:
            profile.undated_count += 1
        else:
            # A date in the future is a parsing or source error, not news.
            if d > today:
                profile.undated_count += 1
                continue
            parsed.append(d)

    profile.dated_count = len(parsed)
    if not parsed:
        return profile

    profile.newest = max(parsed)
    profile.months_since_newest = _months_between(profile.newest, today)

    for d in parsed:
        age = _months_between(d, today)
        if age <= 6:
            profile.within_6_months += 1
        if age <= 12:
            profile.within_12_months += 1
        if age <= 24:
            profile.within_24_months += 1

    return profile


def _months_between(earlier: date, later: date) -> float:
    return (later - earlier).days / 30.44


def recency_factor(profile: RecencyProfile) -> tuple[float, str]:
    """A multiplier for the overall score, plus a sentence explaining it.

    The explanation is returned alongside the number because an unexplained
    adjustment is indistinguishable from the score being wrong.
    """
    if profile.total == 0:
        return 1.0, "No evidence to date-check."

    if profile.dated_count == 0:
        return (
            0.85,
            "None of the evidence carries a date, so how current this is "
            "cannot be verified.",
        )

    months = profile.months_since_newest or 0.0

    if months <= 6:
        factor, phrase = 1.0, f"Freshest evidence is {_describe(months)} old"
    elif months <= 12:
        factor, phrase = 0.95, f"Freshest evidence is {_describe(months)} old"
    elif months <= 24:
        factor, phrase = 0.85, f"Nothing newer than {_describe(months)}"
    else:
        factor, phrase = 0.75, f"Nothing newer than {_describe(months)}"

    # Count recent items rather than their share of the total. A company with
    # a decade of coverage has mostly old evidence by definition; that makes it
    # well documented, not dormant. What matters is whether things are still
    # happening, which is an absolute quantity.
    recent = profile.within_12_months
    if recent >= 3:
        factor += 0.05
        density = f"{recent} developments in the past year"
    elif recent == 0:
        factor -= 0.05
        density = "nothing at all in the past year"
    else:
        density = f"only {recent} development{'s' if recent > 1 else ''} in the past year"

    # Thin date coverage means the picture above rests on very little.
    coverage = profile.dated_count / profile.total
    if coverage < 0.34:
        factor -= 0.05
        density += f", and only {coverage:.0%} of it is dated at all"

    factor = max(MIN_FACTOR, min(MAX_FACTOR, factor))
    return round(factor, 3), f"{phrase}; {density}."


def _describe(months: float) -> str:
    if months < 1:
        return "less than a month"
    if months < 24:
        return f"{round(months)} months"
    return f"{months / 12:.1f} years"
