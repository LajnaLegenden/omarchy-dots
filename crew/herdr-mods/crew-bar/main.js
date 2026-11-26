// Crew bar: ask Haiku to act on Herdr ("split this window", "what are all
// agents working on", "close spaces whose agents are done").
// Enter sends, ↑/↓ walk the history, Esc stops a running request or closes.
// Closing, killing and messaging agents come back as a question: Enter yes, Esc no.
// exec() has a 30 s limit, so `crew bar start` runs Haiku detached and this
// mod follows the request's events file.

import { View, div } from "gpui-kit";
import { v_flex, h_flex, InputState, Input } from "gpui-base";
import { exec, home, focused, spaces, panes, commands, theme, props, closeOverlay, readTextFile, watchFolder } from "herdr";

const SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const POLL_MS = 250;
const HISTORY_SIZE = 50;
const EXAMPLES = ["split this window", "what are all agents working on", "open nordpil in a new space", "rename this space"];
const ROW_ICONS = { ran: "✓", denied: "✕", refused: "⊘", timeout: "…", ask: "?", yes: "…", no: "✕" };

// No PATH fallback: exec may reject on its time limit, and retrying would run a send or post twice.
function runCrew(args) {
  return exec(`${home()}/.local/bin/crew`, args);
}

function getContext() {
  return {
    focused: focused(),
    spaces: spaces().map(({ id, name, folder, machine, active, status, tabs }) => ({
      id, name, folder, machine, active, status,
      tabs: tabs.map(({ id, name, active, status, panes }) => ({ id, name, active, status, panes })),
    })),
    panes: panes().map(({ pane, terminal, mod, tab, title, cwd, status, app, focused, zoomed }) =>
      ({ pane, terminal, mod, tab, title, cwd, status, app, focused, zoomed })),
    commands: commands().map(({ name, args, about }) =>
      ({ name, args: args.map((a) => a.name + (a.required ? "" : "?")), about })),
  };
}

const APPLY_EVENT = {
  text: (state, e) => { state.text += e.text; },
  confirm: (state, e) => state.rows.set(e.n, { ...e, status: "ask" }),
  action: (state, e) => state.rows.set(e.n, { ...state.rows.get(e.n), ...e }),
  done: (state, e) => { state.end = e; },
  error: (state, e) => { state.end = e; },
};

// The last line may still be half written: only whole lines count.
function toRunState(raw) {
  const state = { text: "", rows: new Map(), end: null };
  for (const line of raw.split("\n").slice(0, -1)) {
    let event;
    try {
      event = JSON.parse(line);
    } catch {
      continue;
    }
    APPLY_EVENT[event.type]?.(state, event);
  }
  return state;
}

const toLabel = (argv) => (argv[0] === "herdr-app" && argv[1] === "do" ? argv.slice(2) : argv).join(" ");

const KEY_ACTIONS = {
  escape: (bar, cx) => bar.escape(cx),
  up: (bar) => bar.browse(1),
  down: (bar) => bar.browse(-1),
};

export default class CrewBar extends View {
  init(_props, cx) {
    this.handle = cx.focus_handle();
    this.input = InputState.new({ placeholder: "Ask the crew bar…" });
    this.input.on("submit", (_e, cx) => this.handleSubmit(cx));
    this.input.focus();
    cx.timer.after(600, () => this.input.focus());
    this.history = this.getSavedHistory();
    this.at = -1;
    this.run = null;
    this.poller = null;
    this.watching = false;
    this.reading = false;
  }

  async close() {
    const run = this.run;
    if (run?.id && !run.end) await runCrew(["bar", "cancel", run.id]);
  }

  getSavedHistory() {
    try {
      return JSON.parse(localStorage.getItem("history") ?? "[]");
    } catch {
      return [];
    }
  }

  isRunning() {
    return Boolean(this.run && !this.run.end);
  }

  getPendingConfirm() {
    const run = this.run;
    if (!run) return null;
    return [...run.rows.values()].find((row) => row.status === "ask" && !run.answers.has(row.n)) ?? null;
  }

  handleSubmit(cx) {
    const text = this.input.value().trim();
    // Enter means yes only on an empty input, so a half-typed follow-up never approves a confirm.
    if (this.getPendingConfirm() && !text) return this.answer(true, cx);
    if (!text || this.isRunning()) return;
    this.history = [text, ...this.history.filter((h) => h !== text)].slice(0, HISTORY_SIZE);
    localStorage.setItem("history", JSON.stringify(this.history));
    this.at = -1;
    this.input.set_value("");
    const prev = this.run?.id ?? null;
    const run = { id: null, events: null, request: text, text: "", rows: new Map(), end: null, answers: new Map(), cancelled: false };
    this.run = run;
    const context = JSON.stringify(getContext());
    cx.spawn(async (cx) => this.start(run, context, prev, cx));
    cx.notify();
  }

  async start(run, context, prev, cx) {
    const args = ["bar", "start", "--context", context, ...(prev ? ["--prev", prev] : []), "--", run.request];
    const result = await runCrew(args).catch((error) => ({ code: 1, stdout: "", stderr: String(error) }));
    if (result.code !== 0) {
      run.end = { type: "error", message: result.stderr.trim() || `crew bar start exited ${result.code}` };
      return cx.notify();
    }
    Object.assign(run, JSON.parse(result.stdout));
    if (run.cancelled) return runCrew(["bar", "cancel", run.id]);
    this.watch(run.events, cx);
    this.poller = cx.timer.every(POLL_MS, (cx) => this.poll(cx));
    cx.notify();
  }

  // Wakes on any change in the bar folder; the timer covers missed events.
  watch(eventsPath, cx) {
    if (this.watching) return;
    this.watching = true;
    const folder = eventsPath.slice(0, eventsPath.lastIndexOf("/"));
    cx.spawn(async (cx) => {
      for (;;) {
        await watchFolder(folder);
        await this.poll(cx);
      }
    });
  }

  async poll(cx) {
    const run = this.run;
    if (!run?.events || run.end || this.reading) return;
    this.reading = true;
    const raw = await readTextFile(run.events).catch(() => null).finally(() => { this.reading = false; });
    if (run.end) return;
    Object.assign(run, toRunState(raw ?? ""));
    if (run.end) this.stopPolling();
    cx.notify();
  }

  stopPolling() {
    this.poller?.cancel();
    this.poller = null;
  }

  answer(yes, cx) {
    const row = this.getPendingConfirm();
    if (!row) return;
    const { id, answers } = this.run;
    const answer = yes ? "yes" : "no";
    answers.set(row.n, answer);
    cx.spawn(async () => runCrew(["bar", "answer", id, String(row.n), answer]));
    cx.notify();
  }

  cancel(cx) {
    const run = this.run;
    if (!run || run.end) return;
    run.cancelled = true;
    run.end = { type: "error", message: "stopped" };
    this.stopPolling();
    if (run.id) cx.spawn(async () => runCrew(["bar", "cancel", run.id]));
  }

  escape(cx) {
    if (this.getPendingConfirm()) return this.answer(false, cx);
    if (this.isRunning()) return this.cancel(cx);
    closeOverlay(props().overlay);
  }

  browse(step) {
    const at = Math.max(-1, Math.min(this.at + step, this.history.length - 1));
    if (at === this.at) return;
    this.at = at;
    this.input.set_value(at < 0 ? "" : this.history[at]);
  }

  handleKey(e, cx) {
    const action = KEY_ACTIONS[e.key];
    if (!action) return;
    action(this, cx);
    cx.stop_propagation();
    cx.notify();
  }

  render() {
    const t = theme();
    return v_flex()
      .id("crew-bar")
      .track_focus(this.handle)
      .on_key_down((e, cx) => this.handleKey(e, cx))
      .w_full()
      .min_h(0)
      .p(14)
      .gap(10)
      .bg(t.popover)
      .text_size(12.8)
      .child(this.renderInput(t))
      .child(this.run ? this.renderRun(t, this.run) : this.renderExamples(t));
  }

  renderInput(t) {
    const isRunning = this.isRunning();
    const hint = this.getPendingConfirm() ? "⏎ yes · Esc no" : isRunning ? "Esc stops" : "Esc";
    const mark = isRunning
      ? div().w(14).flex_none().text_color(t.accent).frames(SPINNER, 80).child(SPINNER[0])
      : div().w(14).flex_none().text_color(t.dim).child("›");
    return h_flex()
      .h(36)
      .flex_none()
      .px(10)
      .gap(10)
      .items_center()
      .rounded(9)
      .border_1()
      .border_color(t.accent)
      .bg(t.background)
      .child(mark)
      .child(Input.new(this.input).flex_1().h_full().text_size(12.8).text_color(t.foreground))
      .child(div().flex_none().text_size(11).text_color(t.dim).child(hint));
  }

  renderExamples(t) {
    return div().px(4).text_size(11.5).text_color(t.dim).child(`Try: ${EXAMPLES.join(" · ")}`);
  }

  renderRun(t, run) {
    const { end } = run;
    return v_flex()
      .id("crew-bar-run")
      .max_h(380)
      .overflow_y_scrollbar()
      .px(4)
      .gap(8)
      .child(div().text_size(11.5).text_color(t.dim).child(run.request))
      .children([...run.rows.values()].map((row) => this.renderRow(t, row, run.answers.get(row.n))))
      .when(Boolean(run.text.trim()), (el) => el.child(this.renderText(t.foreground, run.text.trim())))
      .when(Boolean(end && end.type === "error"), (el) => el.child(div().text_color(t.blocked).child(end.message)))
      .when(Boolean(end && end.type === "done" && !run.text.trim() && end.text), (el) => el.child(this.renderText(t.foreground, end.text)))
      .when(Boolean(end && end.type === "done"), (el) =>
        el.child(div().text_size(10.5).text_color(t.dim).child(`${(end.ms / 1000).toFixed(1)} s · first token ${end.first_token_ms ?? "–"} ms`)));
  }

  renderText(color, text) {
    return v_flex().gap(2).text_color(color).children(text.split("\n").map((line) => div().child(line || " ")));
  }

  renderRow(t, row, answer) {
    const status = row.status === "ask" && answer ? answer : row.status;
    const color = { ran: t.done, ask: t.accent, yes: t.accent }[status] ?? t.blocked;
    const line = h_flex()
      .gap(8)
      .items_center()
      .text_size(11.5)
      .child(div().w(14).flex_none().text_color(color).child(ROW_ICONS[status] ?? "·"))
      .child(div().flex_1().min_w(0).truncate().text_color(t.muted).child(row.title ? `${row.title}: ${toLabel(row.argv)}` : toLabel(row.argv)))
      .when(status === "ran" && Boolean(row.code), (el) => el.child(div().flex_none().text_color(t.blocked).child(`exit ${row.code}`)));
    if (status !== "ask") return line;
    return v_flex()
      .gap(6)
      .p(10)
      .rounded(8)
      .border_1()
      .border_color(t.accent)
      .bg(t.raised)
      .child(div().font_semibold().text_color(t.foreground).child(row.title ?? "Run this?"))
      .child(this.renderText(t.muted, row.detail ?? toLabel(row.argv)))
      .child(
        h_flex()
          .justify_end()
          .gap(8)
          .text_size(12)
          .child(this.renderButton(t, `no-${row.n}`, "No  Esc", false))
          .child(this.renderButton(t, `yes-${row.n}`, "Yes  ⏎", true)),
      );
  }

  renderButton(t, id, label, yes) {
    return h_flex()
      .id(id)
      .h(28)
      .px(12)
      .items_center()
      .rounded(7)
      .border_1()
      .border_color(yes ? t.solid : t.input)
      .bg(yes ? t.solid : t.raised)
      .text_color(yes ? t.solid_foreground : t.foreground)
      .cursor_pointer()
      .hover((s) => s.opacity(0.88))
      .on_click((_e, cx) => this.answer(yes, cx))
      .child(label);
  }
}
