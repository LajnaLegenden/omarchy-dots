import QtQuick
import Quickshell.Io

// Runs calendar_events.py on a timer and holds what it last printed.
//
// The calendar URLs are secrets, so they reach the helper through the
// environment rather than argv, which every user can read through ps. The
// helper keeps the last good copy of each feed on disk, so a failed fetch
// still answers with the events it had; `errors` says which calendars that
// happened to.
Item {
  id: root

  // Normalized entries from Agenda.normalizeCalendars().
  property var calendars: []
  property int refreshMinutes: 15

  property var events: []
  property var errors: []
  // True when the helper itself failed (missing Python packages, a crash),
  // as opposed to one feed failing inside it.
  property bool helperFailed: false
  // Epoch ms of the last run that finished, good or bad. Drives the
  // refresh-on-open staleness check.
  property real lastRun: 0

  readonly property bool active: calendars.length > 0
  readonly property string helperPath: decodeURIComponent(String(Qt.resolvedUrl("calendar_events.py")).replace(/^file:\/\//, ""))

  // Settings objects are replaced on every shell.json write, including ones
  // that only cycle the clock format. Comparing the serialized config keeps
  // those from refetching every feed.
  readonly property string configKey: JSON.stringify(calendars.map(function(c) { return [c.url, c.email] }))
  property bool pending: false

  function refresh() {
    if (!active) {
      events = []
      errors = []
      helperFailed = false
      return
    }
    if (proc.running) {
      pending = true
      return
    }
    proc.environment = {
      "LAJNA_CLOCK_CALENDARS": JSON.stringify(calendars.map(function(c) { return { url: c.url, email: c.email } }))
    }
    proc.running = true
  }

  function refreshIfStale(maxAgeMs) {
    if (Date.now() - lastRun > maxAgeMs) refresh()
  }

  onConfigKeyChanged: refresh()
  Component.onCompleted: refresh()

  Timer {
    interval: Math.max(1, root.refreshMinutes) * 60000
    running: root.active
    repeat: true
    onTriggered: root.refresh()
  }

  // Handled when stdout closes rather than on exit: the two signals have no
  // fixed order, and the JSON is only complete once the stream has ended.
  // The helper prints nothing to stdout unless it succeeded, so a crash
  // arrives here as text that does not parse.
  function handleOutput(text) {
    root.lastRun = Date.now()
    var parsed = null
    try {
      parsed = JSON.parse(String(text || ""))
    } catch (e) {
      parsed = null
    }
    if (parsed && Array.isArray(parsed.events) && Array.isArray(parsed.errors)) {
      root.events = parsed.events
      root.errors = parsed.errors
      root.helperFailed = false
      for (var i = 0; i < parsed.errors.length; i++) {
        var error = parsed.errors[i]
        console.warn("lajna.clock: calendar " + error.cal + ": " + error.message + (error.cached ? " (using cached copy)" : ""))
      }
    } else {
      // Keep the last good events on screen; only flag the failure.
      root.helperFailed = true
      Qt.callLater(function() { console.warn("lajna.clock: calendar helper failed: " + String(err.text || "").slice(-500)) })
    }
  }

  Process {
    id: proc
    command: ["/usr/bin/python3", "-I", "-B", root.helperPath]
    // A refresh asked for mid-run (config edited while fetching) runs once
    // this one is fully gone, so it is not swallowed by `running` still
    // being true.
    onRunningChanged: {
      if (!running && root.pending) {
        root.pending = false
        root.refresh()
      }
    }

    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.handleOutput(text)
    }
    stderr: StdioCollector {
      id: err
      waitForEnd: true
    }
  }
}
