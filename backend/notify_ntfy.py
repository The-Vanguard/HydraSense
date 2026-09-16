"""
backend/notify_ntfy.py -- Manual-scenario alert delivery via ntfy.sh.

New capability (not SRS §15's Phase-11 CAP alert system, which stays
stubbed/untouched) added alongside the manual "what-if" risk simulator:
POST a hypothetical feature set, get a REAL FusionModel score back, and if
that score crosses Orange/Red, push a real-time notification via ntfy.sh so
it reaches a phone that's subscribed to the topic.

CLAUDE.md hard constraint: any external API call needs a timeout + fallback,
visibly labeled -- never a silent failure. ntfy.sh needs no API key (topic
name is the shared secret); failures are logged and surfaced in the response,
never swallowed.
"""
from __future__ import annotations
import httpx

NTFY_BASE = "https://ntfy.sh"
NTFY_TOPIC = "hydrasense-alert-ee886045"
TIMEOUT_SECONDS = 8.0

TIER_PRIORITY = {"Red": "urgent", "Orange": "high", "Yellow": "default", "Green": "low"}
TIER_EMOJI = {"Red": "rotating_light", "Orange": "warning", "Yellow": "large_yellow_circle", "Green": "white_check_mark"}


def send_ntfy_alert(title: str, message: str, tier: str) -> dict:
    """Real HTTP POST to ntfy.sh -- timeout + fallback per CLAUDE.md.
    Returns {"sent": bool, "detail": str} -- never raises, never silently
    pretends success on failure."""
    try:
        resp = httpx.post(
            f"{NTFY_BASE}/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                # HTTP header values are ASCII-only by default in httpx --
                # region labels can contain real non-ASCII characters (e.g.
                # the em-dash in "Idukki — Munnar_town"), so encode as UTF-8
                # bytes directly rather than restricting what a title can say.
                "Title": title.encode("utf-8"),
                "Priority": TIER_PRIORITY.get(tier, "default"),
                "Tags": TIER_EMOJI.get(tier, "bell"),
            },
            timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return {"sent": True, "detail": f"ntfy.sh/{NTFY_TOPIC} -> HTTP {resp.status_code}"}
    except httpx.TimeoutException:
        return {"sent": False, "detail": f"ntfy.sh TIMEOUT after {TIMEOUT_SECONDS}s -- alert NOT delivered"}
    except httpx.HTTPStatusError as e:
        return {"sent": False, "detail": f"ntfy.sh HTTP {e.response.status_code} -- alert NOT delivered"}
    except httpx.RequestError as e:
        return {"sent": False, "detail": f"ntfy.sh network error ({e}) -- alert NOT delivered"}
