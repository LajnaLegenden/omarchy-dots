// Pure event math for the calendar popup: config validation, which days get
// dots, the agenda's day groups, and whether an event has ended. Qt-free like
// Model.js; the QML owns time formatting and translation.
//
// Events come from calendar_events.py. Timed events carry epoch-ms start/end;
// all-day events carry local yyyy-MM-dd startDate/endDate, endDate exclusive.

var MAX_CALENDARS = 20
var MAX_DOTS = 3
// A runaway multi-day event must not walk the whole grid for every render.
var MAX_EVENT_DAYS = 62
var MS_PER_DAY = 86400000

function pad2(value) {
  var n = Number(value)
  return (n < 10 ? "0" : "") + n
}

function keyForDate(date) {
  return date.getFullYear() + "-" + pad2(date.getMonth() + 1) + "-" + pad2(date.getDate())
}

function isColor(value) {
  return typeof value === "string" && /^#([0-9a-f]{6}|[0-9a-f]{8})$/i.test(value)
}

// shell.json is hand-edited, so anything malformed is dropped rather than
// half-used. A calendar without a url is skipped; name and color are optional.
function normalizeCalendars(raw) {
  if (!Array.isArray(raw)) return []
  var out = []
  for (var i = 0; i < raw.length && out.length < MAX_CALENDARS; i++) {
    var entry = raw[i]
    if (!entry || typeof entry !== "object") continue
    var url = typeof entry.url === "string" ? entry.url.trim() : ""
    if (url === "") continue
    out.push({
      name: typeof entry.name === "string" && entry.name.trim() !== "" ? entry.name.trim().slice(0, 60) : "",
      url: url,
      email: typeof entry.email === "string" ? entry.email.trim().toLowerCase() : "",
      color: isColor(entry.color) ? entry.color : ""
    })
  }
  return out
}

function clampInt(value, low, high, fallback) {
  var n = Math.round(Number(value))
  if (!isFinite(n)) return fallback
  return Math.min(high, Math.max(low, n))
}

// The clock's own label format decides 12 vs 24 hours: an "H" prints a 24-hour
// hour and an "h" a 12-hour one. A format that prints no hour at all falls back
// to the locale's short time format.
function hourStyle(format) {
  var bare = String(format || "").replace(/'[^']*'/g, "")
  if (/H/.test(bare)) return 24
  if (/h/.test(bare)) return 12
  return 0
}

function uses24Hour(clockFormat, localeTimeFormat) {
  return (hourStyle(clockFormat) || hourStyle(localeTimeFormat) || 24) === 24
}

function parseDateKey(key) {
  var parts = String(key || "").split("-")
  if (parts.length !== 3) return null
  return { year: Number(parts[0]), month: Number(parts[1]) - 1, day: Number(parts[2]) }
}

// All-day ranges walk calendar days in UTC so a DST change cannot repeat or
// skip one; the keys they produce are already local dates.
function allDayKeys(startDate, endDate) {
  var start = parseDateKey(startDate)
  var end = parseDateKey(endDate)
  if (!start) return []
  var cursor = new Date(Date.UTC(start.year, start.month, start.day))
  var stop = end ? Date.UTC(end.year, end.month, end.day) : cursor.getTime() + MS_PER_DAY
  var keys = []
  while (cursor.getTime() < stop && keys.length < MAX_EVENT_DAYS) {
    keys.push(cursor.getUTCFullYear() + "-" + pad2(cursor.getUTCMonth() + 1) + "-" + pad2(cursor.getUTCDate()))
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  if (keys.length === 0) keys.push(String(startDate))
  return keys
}

// Every local day a timed event touches. An event that ends exactly at
// midnight does not spill into the next day.
function timedKeys(startMs, endMs) {
  var start = new Date(startMs)
  var lastMs = endMs > startMs ? endMs - 1 : startMs
  var cursor = new Date(start.getFullYear(), start.getMonth(), start.getDate(), 12)
  var lastKey = keyForDate(new Date(lastMs))
  var keys = []
  while (keys.length < MAX_EVENT_DAYS) {
    var key = keyForDate(cursor)
    keys.push(key)
    if (key === lastKey) break
    cursor.setDate(cursor.getDate() + 1)
  }
  return keys
}

function dayKeys(event) {
  if (!event) return []
  if (event.allDay) return allDayKeys(event.startDate, event.endDate)
  if (typeof event.start !== "number") return []
  return timedKeys(event.start, typeof event.end === "number" ? event.end : event.start)
}

// dayKey -> up to MAX_DOTS colors, one per calendar, in calendar order.
function dotsByDay(events, colors, fallbackColor) {
  var perDay = {}
  var list = Array.isArray(events) ? events : []
  for (var i = 0; i < list.length; i++) {
    var keys = dayKeys(list[i])
    for (var k = 0; k < keys.length; k++) {
      var cals = perDay[keys[k]] || (perDay[keys[k]] = {})
      cals[list[i].cal] = true
    }
  }
  var out = {}
  for (var key in perDay) {
    var indices = Object.keys(perDay[key]).map(Number).sort(function(a, b) { return a - b })
    out[key] = indices.slice(0, MAX_DOTS).map(function(index) {
      return (colors && colors[index]) || fallbackColor
    })
  }
  return out
}

function compareEvents(a, b) {
  if (a.allDay !== b.allDay) return a.allDay ? -1 : 1
  if (!a.allDay && a.start !== b.start) return a.start - b.start
  var at = String(a.title || "")
  var bt = String(b.title || "")
  return at < bt ? -1 : (at > bt ? 1 : 0)
}

// Day groups for the agenda: today plus the next (dayCount - 1) days, with
// days that have no events left out. Each group carries its offset from today
// so the QML can say "Today"/"Tomorrow" without re-deriving dates.
function agendaGroups(events, today, dayCount) {
  var count = Math.max(1, Number(dayCount) || 1)
  var wanted = {}
  var order = []
  var cursor = new Date(today.getFullYear(), today.getMonth(), today.getDate(), 12)
  for (var d = 0; d < count; d++) {
    var key = keyForDate(cursor)
    wanted[key] = { key: key, offset: d, date: new Date(cursor.getTime()), events: [] }
    order.push(key)
    cursor.setDate(cursor.getDate() + 1)
  }

  var list = Array.isArray(events) ? events : []
  for (var i = 0; i < list.length; i++) {
    var keys = dayKeys(list[i])
    for (var k = 0; k < keys.length; k++)
      if (wanted[keys[k]]) wanted[keys[k]].events.push(list[i])
  }

  var groups = []
  for (var g = 0; g < order.length; g++) {
    var group = wanted[order[g]]
    if (group.events.length === 0) continue
    group.events.sort(compareEvents)
    groups.push(group)
  }
  return groups
}

// "ended" dims a row and "now" highlights it. All-day events are neither: an
// all-day row lit up from midnight to midnight would only be noise.
function eventState(event, nowMs) {
  if (!event || event.allDay) return "allDay"
  if (nowMs >= event.end && nowMs >= event.start) return "ended"
  if (nowMs >= event.start) return "now"
  return "upcoming"
}

// How a row's time column reads on a given day:
//   allDay  the event is all-day, or covers this day end to end
//   range   starts and ends on this day
//   from    starts on this day, ends on a later one
//   until   started on an earlier day, ends on this one
function timeSpan(event, dayKey) {
  if (!event || event.allDay) return "allDay"
  var startKey = keyForDate(new Date(event.start))
  var endKey = keyForDate(new Date(event.end > event.start ? event.end - 1 : event.start))
  var startsToday = startKey === dayKey
  var endsToday = endKey === dayKey
  if (startsToday && endsToday) return "range"
  if (startsToday) return "from"
  if (endsToday) return "until"
  return "allDay"
}

// Defense in depth: the helper already allowlists hosts, so this only refuses
// anything that is not a plain https URL before it reaches the browser.
function isJoinUrl(url) {
  return typeof url === "string" && url.length <= 2048 && /^https:\/\/[^\s]+$/.test(url)
}
