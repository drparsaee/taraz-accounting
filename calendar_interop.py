"""Offline, bounded iCalendar (.ics) file interchange for Madar Desk tasks.

This is a deliberately narrow calendar adapter, not a calendar client. Export
only task IDs (as opaque hashes), titles and Gregorian due dates. Import only
preview records. A host must authorize and validate any later task creation.
No disk, network, OAuth, notifications or shared-state mutation occur here.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta, timezone

MAX_ICS_BYTES = 2_000_000
MAX_EVENTS = 1_000
MAX_LINES = 25_000
MAX_PHYSICAL_LINE_BYTES = 16_384
MAX_LOGICAL_LINE_BYTES = 32_768
MAX_TITLE_CHARS = 300
MAX_CALENDAR_NAME_CHARS = 100
MAX_UID_BYTES = 512
MAX_IMPORT_KEYS = 20_000
MIN_YEAR = 1900
MAX_YEAR = 2100

_IDENTIFIER = re.compile(r"[A-Za-z0-9-]{1,80}\Z", re.ASCII)
_TIME = re.compile(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z?)\Z", re.ASCII)
_DATE = re.compile(r"(\d{4})(\d{2})(\d{2})\Z", re.ASCII)
_KEY = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_TZID = re.compile(r"[/A-Za-z0-9_.+\- ]{1,128}\Z", re.ASCII)
_LANGUAGE = re.compile(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8}){0,4}\Z", re.ASCII)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class CalendarInteropError(ValueError):
    """Invalid or oversized iCalendar input/output."""


def _safe_date(value: object, label: str, *, allow_end: bool = False) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value, re.ASCII):
        raise CalendarInteropError(f"{label}: expected Gregorian ISO YYYY-MM-DD")
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise CalendarInteropError(f"{label}: invalid Gregorian date") from exc
    if not MIN_YEAR <= result.year <= MAX_YEAR + int(allow_end):
        raise CalendarInteropError(f"{label}: year outside supported range")
    return result


def _clean_title(value: object, label: str, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise CalendarInteropError(f"{label}: expected string of up to {limit} characters")
    normalized = value.strip()
    if not normalized or _CONTROL.search(normalized):
        raise CalendarInteropError(f"{label}: invalid or control characters")
    return normalized


def _escape_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\r\n", "\n").replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(";", "\\;").replace(",", "\\,")
    )


def _unescape_text(value: str) -> str:
    result: list[str] = []
    offset = 0
    while offset < len(value):
        c = value[offset]
        if c != "\\":
            result.append(c)
        else:
            offset += 1
            if offset >= len(value):
                raise CalendarInteropError("iCalendar text has trailing escape")
            next_char = value[offset]
            if next_char in ("n", "N"):
                result.append("\n")
            elif next_char in ("\\", ",", ";"):
                result.append(next_char)
            else:
                raise CalendarInteropError("unsupported iCalendar text escape")
        offset += 1
    return "".join(result)


def _fold(line: str) -> list[str]:
    """Fold at 75 UTF-8 octets without cutting a multibyte character."""
    result: list[str] = []
    current = ""
    used = 0
    for char in line:
        encoded = len(char.encode("utf-8"))
        if used + encoded > 75:
            result.append(current)
            current = " "  # RFC 5545 continuation consumes one octet.
            used = 1
        current += char
        used += encoded
    result.append(current)
    return result


def export_ics(
    tasks: Iterable[Mapping[str, object]],
    *,
    calendar_name: str = "Madar Desk",
    now: datetime | None = None,
) -> bytes:
    """Generate UTF-8 CRLF .ics for non-archived tasks with dueDate.

    Only id, title, dueDate and archived are inspected. Description, project,
    assignees, comments, finance, invoices, attachment paths and arbitrary
    extension metadata are excluded by construction.

    dueDate is always Gregorian ISO regardless of the UI's Persian formatting.
    All-day DTEND is the next day (exclusive). Missing dueDate is skipped.
    """
    name = _clean_title(calendar_name, "calendar_name", MAX_CALENDAR_NAME_CHARS)
    if now is None:
        now = datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise CalendarInteropError("now: expected timezone-aware datetime")
    timestamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if isinstance(tasks, (str, bytes, bytearray, Mapping)):
        raise CalendarInteropError("tasks: expected iterable of task objects")
    try:
        iterator = iter(tasks)
    except TypeError as exc:
        raise CalendarInteropError("tasks: expected iterable") from exc

    events: list[tuple[str, str, date]] = []
    seen_ids: set[str] = set()
    for index, task in enumerate(iterator):
        if index >= MAX_EVENTS:
            raise CalendarInteropError("too many source tasks")
        if not isinstance(task, Mapping):
            raise CalendarInteropError(f"tasks[{index}]: expected object")
        # Treat an invalid archived flag as an error, not an accidental export.
        archived = task.get("archived", False)
        if type(archived) is not bool:
            raise CalendarInteropError(f"tasks[{index}].archived: expected bool")
        if archived:
            continue
        raw = task.get("dueDate")
        if raw is None or raw == "":
            continue
        due = _safe_date(raw, f"tasks[{index}].dueDate")
        identifier = task.get("id")
        if not isinstance(identifier, str) or not identifier or len(identifier) > 512:
            raise CalendarInteropError(f"tasks[{index}].id: invalid")
        if identifier in seen_ids:
            raise CalendarInteropError("duplicate task id in export")
        seen_ids.add(identifier)
        title = _clean_title(task.get("title"), f"tasks[{index}].title", MAX_TITLE_CHARS)
        uid = hashlib.sha256(identifier.encode("utf-8")).hexdigest() + "@madar.invalid"
        events.append((uid, title, due))
    events.sort(key=lambda event: (event[2], event[0]))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Madar Desk//Offline Calendar Interop 1.0//EN",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:" + _escape_text(name),
    ]
    for uid, title, day in events:
        if day.year >= 9999:
            raise CalendarInteropError("DTEND: unsupported calendar date")
        lines.extend((
            "BEGIN:VEVENT",
            "UID:" + uid,
            "DTSTAMP:" + timestamp,
            "DTSTART;VALUE=DATE:" + day.strftime("%Y%m%d"),
            "DTEND;VALUE=DATE:" + (day + timedelta(days=1)).strftime("%Y%m%d"),
            "SUMMARY:" + _escape_text(title),
            "END:VEVENT",
        ))
    lines.append("END:VCALENDAR")
    data = ("\r\n".join(piece for line in lines for piece in _fold(line)) + "\r\n").encode("utf-8")
    if len(data) > MAX_ICS_BYTES:
        raise CalendarInteropError("export exceeds maximum .ics size")
    return data


def _unfold(blob: bytes | str) -> list[str]:
    if isinstance(blob, str):
        if len(blob) > MAX_ICS_BYTES:
            raise CalendarInteropError("iCalendar exceeds maximum size")
        try:
            encoded = blob.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise CalendarInteropError("iCalendar text must be valid UTF-8") from exc
    elif isinstance(blob, bytes):
        encoded = blob
    else:
        raise CalendarInteropError("iCalendar input must be UTF-8 bytes or str")
    if len(encoded) > MAX_ICS_BYTES:
        raise CalendarInteropError("iCalendar exceeds maximum size")
    try:
        text = encoded.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CalendarInteropError("iCalendar input must be valid UTF-8") from exc
    if "\x00" in text or ("\r" in text.replace("\r\n", "")):
        raise CalendarInteropError("invalid iCalendar newline or NUL")
    physical = text.replace("\r\n", "\n").split("\n")
    if physical[-1] == "":
        physical.pop()
    if len(physical) > MAX_LINES:
        raise CalendarInteropError("too many iCalendar lines")
    output: list[str] = []
    for line in physical:
        if len(line.encode("utf-8")) > MAX_PHYSICAL_LINE_BYTES:
            raise CalendarInteropError("oversized iCalendar physical line")
        if line.startswith((" ", "\t")):
            if not output:
                raise CalendarInteropError("orphaned folded line")
            output[-1] += line[1:]
        else:
            output.append(line)
        if len(output[-1].encode("utf-8")) > MAX_LOGICAL_LINE_BYTES:
            raise CalendarInteropError("oversized unfolded iCalendar line")
    return output


def _split_property(line: str) -> tuple[str, dict[str, str], str]:
    quote = False
    colon_at = -1
    for index, char in enumerate(line):
        if char == '"':
            quote = not quote
        elif char == ":" and not quote:
            colon_at = index
            break
    if colon_at < 1 or quote:
        raise CalendarInteropError("malformed iCalendar property")
    header, value = line[:colon_at], line[colon_at + 1:]
    parts: list[str] = []
    quoted = False
    previous = 0
    for pos, char in enumerate(header):
        if char == '"':
            quoted = not quoted
        elif char == ";" and not quoted:
            parts.append(header[previous:pos])
            previous = pos + 1
    if quoted:
        raise CalendarInteropError("unbalanced quoted property parameter")
    parts.append(header[previous:])
    name = parts[0].upper()
    if not _IDENTIFIER.fullmatch(name):
        raise CalendarInteropError("invalid iCalendar property name")
    parameters: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            raise CalendarInteropError("invalid iCalendar property parameter")
        key, raw = part.split("=", 1)
        key = key.upper()
        if not _IDENTIFIER.fullmatch(key) or key in parameters:
            raise CalendarInteropError("invalid or duplicated property parameter")
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            raw = raw[1:-1]
        if not raw or '"' in raw or "\n" in raw or "\r" in raw:
            raise CalendarInteropError("invalid property parameter value")
        parameters[key] = raw
    return name, parameters, value


def _parse_start(value: str, params: dict[str, str], *, allow_end: bool = False) -> tuple[str, str, str, str]:
    """Return (YYYY-MM-DD, dateKind, HH:MM or '', timezone label).

    A timed event is represented by its *wall calendar date* in DTSTART,
    including for TZID and UTC. We do not convert across zones, which would
    silently alter a date-only Madar dueDate when the user's timezone differs.
    """
    if set(params) - {"VALUE", "TZID"}:
        raise CalendarInteropError("unsupported date parameter")
    kind = params.get("VALUE", "DATE-TIME").upper()
    if kind == "DATE":
        if "TZID" in params:
            raise CalendarInteropError("all-day date cannot contain TZID")
        match = _DATE.fullmatch(value)
        if not match:
            raise CalendarInteropError("invalid all-day DTSTART")
        raw = "-".join(match.groups())
        return _safe_date(raw, "DTEND" if allow_end else "DTSTART", allow_end=allow_end).isoformat(), "date", "", ""
    if kind != "DATE-TIME":
        raise CalendarInteropError("unsupported temporal VALUE")
    match = _TIME.fullmatch(value)
    if not match:
        raise CalendarInteropError("unsupported DTSTART timestamp")
    year, month, day, hour, minute, second, zulu = match.groups()
    raw = f"{year}-{month}-{day}"
    day_value = _safe_date(raw, "DTEND" if allow_end else "DTSTART", allow_end=allow_end)
    try:
        datetime(day_value.year, day_value.month, day_value.day, int(hour), int(minute), int(second))
    except ValueError as exc:
        raise CalendarInteropError("invalid DTSTART clock time") from exc
    tzid = params.get("TZID", "")
    if tzid and (not _TZID.fullmatch(tzid) or ".." in tzid or tzid.startswith("/")):
        raise CalendarInteropError("invalid TZID")
    if zulu and tzid:
        raise CalendarInteropError("UTC timestamp cannot specify TZID")
    return raw, "datetime", f"{hour}:{minute}", "UTC" if zulu else tzid


def _extract_event(properties: dict[str, list[tuple[dict[str, str], str]]]) -> dict[str, str]:
    for property_name in ("UID", "DTSTART", "DTEND", "SUMMARY", "STATUS", "CLASS"):
        if len(properties.get(property_name, [])) > 1:
            raise CalendarInteropError(f"duplicate {property_name}")
    if any(key in properties for key in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID")):
        raise CalendarInteropError("recurring event not supported")
    if properties.get("STATUS", [({}, "")])[0][1].upper() == "CANCELLED":
        raise CalendarInteropError("cancelled event")
    if properties.get("CLASS", [({}, "")])[0][1].upper() in ("PRIVATE", "CONFIDENTIAL"):
        raise CalendarInteropError("private event excluded")
    uid_field = properties.get("UID", [])
    summary_field = properties.get("SUMMARY", [])
    start_field = properties.get("DTSTART", [])
    if not uid_field or not summary_field or not start_field:
        raise CalendarInteropError("VEVENT requires UID, DTSTART, SUMMARY")
    summary_params = summary_field[0][0]
    if uid_field[0][0] or set(summary_params) - {"LANGUAGE"} or (
        "LANGUAGE" in summary_params and not _LANGUAGE.fullmatch(summary_params["LANGUAGE"])
    ):
        raise CalendarInteropError("unsupported UID/SUMMARY parameters")
    uid = uid_field[0][1]
    if not uid or len(uid.encode("utf-8")) > MAX_UID_BYTES or _CONTROL.search(uid):
        raise CalendarInteropError("invalid UID")
    title = _clean_title(_unescape_text(summary_field[0][1]), "SUMMARY", MAX_TITLE_CHARS)
    event_date, date_kind, local_time, zone = _parse_start(*start_field[0][::-1])
    # Check DTEND even though task dueDate only captures the DTSTART calendar
    # day. Do not import malformed windows (or incomparable timezones).
    if properties.get("DTEND"):
        end_date, end_kind, end_time, end_zone = _parse_start(
            *properties["DTEND"][0][::-1], allow_end=True
        )
        if end_kind != date_kind or (end_zone != zone):
            raise CalendarInteropError("DTEND must have matching time kind/timezone")
        if date_kind == "date":
            if end_date <= event_date:
                raise CalendarInteropError("DTEND is not after DTSTART")
        elif (end_date, end_time) <= (event_date, local_time):
            raise CalendarInteropError("DTEND is not after DTSTART")
    return {
        "source_key": hashlib.sha256(uid.encode("utf-8")).hexdigest(),
        "title": title,
        "dueDate": event_date,
        "dateKind": date_kind,
        "time": local_time,
        "timezone": zone,
    }


def import_ics(
    content: bytes | str,
    *,
    existing_keys: Iterable[str] = (),
) -> dict[str, list[dict[str, object]]]:
    """Safely preview VEVENTs from Google/Outlook .ics, without mutating tasks.

    Each accepted event is {"source_key", "title", "dueDate", "dateKind",
    "time", "timezone"}. Persist source_key as calendarSourceKey after an
    independently authorized host import, then pass existing_keys on later
    imports for idempotency. Never persist raw UID (may include email).
    """
    if isinstance(existing_keys, (str, bytes, Mapping)):
        raise CalendarInteropError("existing_keys: expected iterable of hashes")
    try:
        key_iterator = iter(existing_keys)
    except TypeError as exc:
        raise CalendarInteropError("existing_keys: expected iterable") from exc
    known: set[str] = set()
    for index, key in enumerate(key_iterator):
        if index >= MAX_IMPORT_KEYS:
            raise CalendarInteropError("too many existing calendar keys")
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise CalendarInteropError("invalid existing calendar source key")
        known.add(key)

    lines = _unfold(content)
    stack: list[str] = []
    events: list[dict[str, str]] = []
    skipped: list[dict[str, object]] = []
    current: dict[str, list[tuple[dict[str, str], str]]] | None = None
    index = 0
    saw_version = False
    root_count = 0
    cancellation = False
    for line in lines:
        if not line:
            raise CalendarInteropError("blank iCalendar content line")
        name, params, value = _split_property(line)
        if name == "BEGIN":
            if params or not _IDENTIFIER.fullmatch(value.upper()):
                raise CalendarInteropError("invalid BEGIN")
            component = value.upper()
            if not stack and component != "VCALENDAR":
                raise CalendarInteropError("expected VCALENDAR root")
            if not stack:
                root_count += 1
                if root_count != 1:
                    raise CalendarInteropError("multiple VCALENDAR roots")
            if stack and stack[0] != "VCALENDAR":
                raise CalendarInteropError("invalid calendar hierarchy")
            if len(stack) >= 8:
                raise CalendarInteropError("nested iCalendar components too deep")
            if component == "VCALENDAR" and stack:
                raise CalendarInteropError("nested VCALENDAR")
            if component == "VEVENT" and stack != ["VCALENDAR"]:
                raise CalendarInteropError("VEVENT must be directly under VCALENDAR")
            stack.append(component)
            if stack == ["VCALENDAR", "VEVENT"]:
                if index >= MAX_EVENTS:
                    raise CalendarInteropError("too many VEVENTs")
                current = {}
                index += 1
            continue
        if name == "END":
            if params or not stack or value.upper() != stack[-1]:
                raise CalendarInteropError("unbalanced iCalendar component")
            if stack == ["VCALENDAR", "VEVENT"]:
                assert current is not None
                try:
                    event = _extract_event(current)
                    key = event["source_key"]
                    if key in known:
                        skipped.append({"index": index, "reason": "duplicate_source"})
                    else:
                        known.add(key)
                        events.append(event)
                except CalendarInteropError as exc:
                    skipped.append({"index": index, "reason": str(exc)})
                current = None
            stack.pop()
            continue
        if not stack:
            raise CalendarInteropError("content outside VCALENDAR")
        if stack == ["VCALENDAR"] and name == "VERSION":
            if params or value != "2.0" or saw_version:
                raise CalendarInteropError("unsupported or duplicate VERSION")
            saw_version = True
        if stack == ["VCALENDAR"] and name == "CALSCALE":
            if params or value.upper() != "GREGORIAN":
                raise CalendarInteropError("only Gregorian ICS calendar scale is supported")
        if stack == ["VCALENDAR"] and name == "METHOD" and value.upper() == "CANCEL":
            cancellation = True
        if stack == ["VCALENDAR", "VEVENT"]:
            assert current is not None
            current.setdefault(name, []).append((params, value))
    if stack or not saw_version or not lines or lines[0].upper() != "BEGIN:VCALENDAR" or lines[-1].upper() != "END:VCALENDAR":
        raise CalendarInteropError("incomplete or unsupported VCALENDAR")
    if cancellation:
        raise CalendarInteropError("cancellation calendar cannot create tasks")
    return {"events": events, "skipped": skipped}
