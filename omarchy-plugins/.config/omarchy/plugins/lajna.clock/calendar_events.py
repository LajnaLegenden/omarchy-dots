#!/usr/bin/env python3
"""Fetch ICS feeds for the clock's calendar popup and print normalized events.

The panel runs this with /usr/bin/python3 -I -B. Calendars come in through the
LAJNA_CLOCK_CALENDARS environment variable, not argv: the URLs are secrets and
argv is readable by every user through ps.

    LAJNA_CLOCK_CALENDARS  JSON list of {"url": str, "email": str}; list order
                           is the calendar index the panel maps colors with
    LAJNA_CLOCK_CACHE_DIR  where the last good copy of each feed is kept
                           (default ~/.cache/omarchy/lajna.clock)

Output on stdout is one JSON object:

    {"events": [{"cal", "uid", "title", "allDay", "start", "end",
                 "startDate", "endDate", "url"}],
     "errors": [{"cal", "message", "cached"}]}

Timed events carry start/end as epoch milliseconds. All-day events carry
startDate/endDate as local yyyy-MM-dd, with endDate exclusive as in ICS.

Feed text is untrusted: every string is bounded and stripped of control
characters, and only https meeting links on a fixed host allowlist survive.
"""

import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

import icalendar
import recurring_ical_events

MAX_CALENDARS = 20
MAX_FEED_BYTES = 10 * 1024 * 1024
MAX_EVENTS = 5000
MAX_TITLE = 200
MAX_UID = 512
MAX_URL = 2048
FETCH_TIMEOUT = 10
USER_AGENT = "lajna.clock/1.0"

MEETING_HOSTS = ("meet.google.com", "zoom.us", "teams.microsoft.com")
# Searched in this order: the dedicated conference field beats a link someone
# pasted into the description.
MEETING_FIELDS = ("X-GOOGLE-CONFERENCE", "URL", "LOCATION", "DESCRIPTION")
LINK_PATTERN = re.compile(r"https://[^\s<>\"'()\[\]{}]+", re.IGNORECASE)
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f  ]+")


class FeedError(Exception):
    """A feed could not be fetched or parsed; the message is shown in logs."""


# ---- Fetching


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme.lower() != "https":
            raise FeedError("redirect to a non-https URL")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_HttpsOnlyRedirects)


def normalize_feed_url(url):
    """Return the URL to fetch, or raise FeedError for an unsupported scheme.

    webcal:// is https in disguise. file:// is allowed so a local test feed can
    stand in for a real one; plain http is not, since the URL is a secret.
    """
    parts = urllib.parse.urlsplit(str(url).strip())
    scheme = parts.scheme.lower()
    if scheme == "webcal":
        return urllib.parse.urlunsplit(("https",) + tuple(parts[1:]))
    if scheme in ("https", "file"):
        return parts.geturl()
    raise FeedError("unsupported URL scheme (use https, webcal or file)")


def fetch_feed(url):
    """Download one feed and return its bytes, bounded by MAX_FEED_BYTES."""
    target = normalize_feed_url(url)
    if target.startswith("file:"):
        path = urllib.parse.unquote(urllib.parse.urlsplit(target).path)
        try:
            with open(path, "rb") as handle:
                data = handle.read(MAX_FEED_BYTES + 1)
        except OSError as error:
            raise FeedError(f"cannot read file: {error.strerror}") from error
    else:
        request = urllib.request.Request(target, headers={"User-Agent": USER_AGENT})
        try:
            with _opener.open(request, timeout=FETCH_TIMEOUT) as response:
                data = response.read(MAX_FEED_BYTES + 1)
        except urllib.error.HTTPError as error:
            raise FeedError(f"HTTP {error.code}") from error
        except urllib.error.URLError as error:
            reason = error.reason
            if isinstance(reason, FeedError):
                raise reason from error
            raise FeedError(f"unreachable: {reason}") from error
        except TimeoutError as error:
            raise FeedError("timed out") from error
        except OSError as error:
            raise FeedError(f"network error: {error}") from error
    if len(data) > MAX_FEED_BYTES:
        raise FeedError("feed larger than 10 MB")
    return data


# ---- Cache


def cache_path(cache_dir, url):
    digest = hashlib.sha256(str(url).encode("utf-8")).hexdigest()
    return os.path.join(cache_dir, digest + ".ics")


def read_cache(cache_dir, url):
    try:
        with open(cache_path(cache_dir, url), "rb") as handle:
            return handle.read(MAX_FEED_BYTES + 1)
    except OSError:
        return None


def write_cache(cache_dir, url, data):
    """Atomically replace the cached copy. Calendar contents are private: 0600."""
    try:
        os.makedirs(cache_dir, mode=0o700, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=cache_dir, prefix=".feed-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp, cache_path(cache_dir, url))
        except BaseException:
            os.unlink(tmp)
            raise
    except OSError:
        pass  # A missing cache only costs the offline fallback.


# ---- Parsing


def clean_text(value, limit):
    text = CONTROL_CHARS.sub(" ", str(value or ""))
    return " ".join(text.split())[:limit]


def parse_calendar(data):
    try:
        return icalendar.Calendar.from_ical(data)
    except Exception as error:  # icalendar raises a mix of ValueError and friends
        raise FeedError("invalid calendar data") from error


def meeting_url(component):
    """First https link on an allowed meeting host, or ""."""
    for field in MEETING_FIELDS:
        value = component.get(field)
        if value is None:
            continue
        for match in LINK_PATTERN.finditer(str(value)):
            candidate = match.group(0).rstrip(".,;:!?")
            if len(candidate) > MAX_URL:
                continue
            try:
                parts = urllib.parse.urlsplit(candidate)
                port = parts.port
            except ValueError:
                continue
            host = (parts.hostname or "").lower()
            if parts.scheme.lower() != "https" or parts.username or parts.password or port:
                continue
            if any(host == allowed or host.endswith("." + allowed) for allowed in MEETING_HOSTS):
                return candidate
    return ""


def _attendees(component):
    value = component.get("ATTENDEE")
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def declined_by(component, email):
    if not email:
        return False
    for attendee in _attendees(component):
        address = str(attendee).strip().lower()
        if address.startswith("mailto:"):
            address = address[len("mailto:"):]
        if address == email and str(attendee.params.get("PARTSTAT", "")).upper() == "DECLINED":
            return True
    return False


def _epoch_ms(value):
    # A naive (floating) datetime means local wall time, which is exactly how
    # datetime.timestamp() reads one.
    return int(value.timestamp() * 1000)


def normalize_event(component, cal_index, email):
    """Turn one expanded occurrence into the panel's event dict, or None."""
    if str(component.get("STATUS", "")).upper() == "CANCELLED":
        return None
    if declined_by(component, email):
        return None
    try:
        start = component.start
    except Exception:
        return None
    try:
        end = component.end
    except Exception:
        end = None

    event = {
        "cal": cal_index,
        "uid": clean_text(component.get("UID", ""), MAX_UID),
        "title": clean_text(component.get("SUMMARY", ""), MAX_TITLE),
        "allDay": False,
        "start": None,
        "end": None,
        "startDate": None,
        "endDate": None,
        "url": meeting_url(component),
    }

    if isinstance(start, dt.datetime):
        if end is None or not isinstance(end, dt.datetime) or end < start:
            end = start
        event["start"] = _epoch_ms(start)
        event["end"] = _epoch_ms(end)
    else:
        if end is None or isinstance(end, dt.datetime) or end <= start:
            end = start + dt.timedelta(days=1)
        event["allDay"] = True
        event["startDate"] = start.isoformat()
        event["endDate"] = end.isoformat()
    return event


def expansion_window(today):
    """First day of last month through the first day of the month 3 ahead.

    That covers the month on screen when the popup opens, one month back and
    two forward, which is what the grid dots promise.
    """
    first = today.replace(day=1)
    start = (first - dt.timedelta(days=1)).replace(day=1)
    month_index = first.month - 1 + 3
    end = dt.date(first.year + month_index // 12, month_index % 12 + 1, 1)
    return start, end


def expand(calendar, start, end):
    query = recurring_ical_events.of(calendar, skip_bad_series=True)
    return query.between(start, end)


# ---- Orchestration


def load_feed(cal_index, calendar, cache_dir, fetcher):
    """Return (parsed calendar or None, error dict or None) for one config entry."""
    url = calendar.get("url", "")
    try:
        data = fetcher(url)
        parsed = parse_calendar(data)
        write_cache(cache_dir, url, data)
        return parsed, None
    except FeedError as error:
        message = str(error)
    except Exception as error:  # A surprise in one feed must not sink the others.
        message = f"unexpected error: {type(error).__name__}"

    cached = read_cache(cache_dir, url)
    if cached is not None and len(cached) <= MAX_FEED_BYTES:
        try:
            return parse_calendar(cached), {"cal": cal_index, "message": message, "cached": True}
        except FeedError:
            pass
    return None, {"cal": cal_index, "message": message, "cached": False}


def collect(calendars, today, cache_dir, fetcher=fetch_feed):
    start, end = expansion_window(today)
    calendars = list(calendars)[:MAX_CALENDARS]
    events, errors, seen = [], [], set()

    workers = max(1, min(8, len(calendars)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        loaded = list(pool.map(lambda pair: load_feed(pair[0], pair[1], cache_dir, fetcher), enumerate(calendars)))

    # Calendars are walked in config order, so when the same event sits in two
    # of them the first calendar's copy is the one kept.
    for cal_index, (parsed, error) in enumerate(loaded):
        if error:
            errors.append(error)
        if parsed is None:
            continue
        email = str(calendars[cal_index].get("email") or "").strip().lower()
        try:
            occurrences = expand(parsed, start, end)
        except Exception:
            errors.append({"cal": cal_index, "message": "could not expand recurring events", "cached": False})
            continue
        for component in occurrences:
            event = normalize_event(component, cal_index, email)
            if event is None:
                continue
            if event["uid"]:
                key = (event["uid"], event["start"], event["startDate"])
                if key in seen:
                    continue
                seen.add(key)
            events.append(event)
            if len(events) >= MAX_EVENTS:
                break

    events.sort(key=lambda e: (e["startDate"] or "", e["start"] or 0, e["title"]))
    return {"events": events, "errors": errors}


def read_config(environ):
    try:
        raw = json.loads(environ.get("LAJNA_CLOCK_CALENDARS", "[]"))
    except ValueError:
        return []
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict) and isinstance(entry.get("url"), str)]


def main():
    cache_dir = os.environ.get("LAJNA_CLOCK_CACHE_DIR") or os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "omarchy", "lajna.clock"
    )
    result = collect(read_config(os.environ), dt.date.today(), cache_dir)
    json.dump(result, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
