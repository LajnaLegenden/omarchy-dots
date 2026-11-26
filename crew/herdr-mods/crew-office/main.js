// A crew office as a chat room: the members and what they are doing, the
// channel's posts (newest first, under the composer) and a composer that posts
// as you. Props: { office }; without one, the first running office.
// Posts come from `crew read <office> --json`, the header from the office file;
// both reload when <state>/crew/channels or offices change.
// Newest first because a plain scroll area can't be pinned to its bottom.

import { View, div } from "gpui-kit";
import { v_flex, h_flex, InputState, Input, TextView } from "gpui-base";
import { agents, terminals, exec, home, props, theme, run, notify, readTextFile, watchFolder, nextCommand } from "herdr";

const ROLES = ["pm", "ux-designer", "ux-reviewer", "developer", "tester"];
const ROLE_LOOK = {
  pm: { badge: "PM", color: "ansi5" },
  "ux-designer": { badge: "UX", color: "ansi6" },
  "ux-reviewer": { badge: "UR", color: "ansi3" },
  developer: { badge: "DV", color: "ansi4" },
  tester: { badge: "QA", color: "ansi2" },
  human: { badge: "ME", color: "accent" },
};
const STATE_COLOR = { running: "done", paused: "blocked", stopped: "dim" };
const SPIN = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const HUMAN_REFS = ["you", "human", "user"];
const MENTION = /(^|[^\w@/])@([a-zA-Z0-9_/-]+)/g;
const TYPING_MENTION = /(?:^|\s)@([\w-]*)$/;

const pad = (n) => String(n).padStart(2, "0");
const toClock = (iso) => {
  const d = new Date(iso);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const isForYou = (post) => (post.mentions ?? []).some((m) => HUMAN_REFS.includes(m.toLowerCase()));
const isAlert = (post) => post.from !== "human" && (isForYou(post) || (post.from === "crew" && post.text.startsWith("Paused after")));
const toMarkdown = (text) => text.replace(MENTION, (_m, before, ref) => `${before}**@${ref}**`);
const getAuthor = (post) => (post.from === "human" ? "you" : post.role ?? post.from_label);
const getLook = (post) => ROLE_LOOK[post.from === "human" ? "human" : post.role] ?? { badge: post.from.slice(0, 2).toUpperCase(), color: "muted" };

// No PATH fallback: exec may reject on its time limit, and retrying would run a send or post twice.
function runCrew(args) {
  return exec(`${home()}/.local/bin/crew`, args);
}

async function getFirstLiveOffice() {
  const result = await runCrew(["office", "ls", "--json"]);
  if (result.code !== 0) return null;
  const { offices } = JSON.parse(result.stdout);
  return (offices.find((o) => o.state === "running") ?? offices.find((o) => o.state === "paused"))?.name ?? null;
}

export default class CrewOffice extends View {
  init(_props, cx) {
    this.name = props()?.office ?? null;
    this.office = null;
    this.posts = [];
    this.seen = null;
    this.draft = "";
    this.input = InputState.new({ placeholder: "Message the office: @pm, @developer, @team…" });
    this.input.on("change", (_e, cx) => {
      this.draft = this.input.value();
      cx.notify();
    });
    this.input.on("submit", (_e, cx) => this.send(cx));
    this.handle = cx.focus_handle();
    cx.spawn(async (cx) => {
      const result = await exec("sh", ["-c", 'printf %s "${XDG_STATE_HOME:-$HOME/.local/state}"']);
      this.stateDir = `${result.stdout.trim()}/crew`;
      await exec("mkdir", ["-p", `${this.stateDir}/channels`, `${this.stateDir}/offices`]);
      this.reload(cx);
      this.watch(`${this.stateDir}/channels`, cx);
      this.watch(`${this.stateDir}/offices`, cx);
    });
    cx.spawn(async () => {
      for (;;) {
        if ((await nextCommand()) === "focus") this.input.focus();
      }
    });
  }

  watch(dir, cx) {
    cx.spawn(async (cx) => {
      try {
        for (;;) {
          await watchFolder(dir);
          this.reload(cx);
        }
      } catch {
        if (this.polling) return;
        this.polling = true;
        cx.timer.every(5000, (cx) => this.reload(cx));
      }
    });
  }

  reload(cx) {
    if (this.loading) {
      this.again = true;
      return;
    }
    this.loading = true;
    cx.spawn(async (cx) => {
      try {
        await this.load();
        this.error = null;
      } catch (error) {
        this.error = String(error?.message ?? error);
      }
      this.loading = false;
      cx.notify();
      if (!this.again) return;
      this.again = false;
      this.reload(cx);
    });
  }

  async load() {
    this.name = this.name ?? (await getFirstLiveOffice());
    if (!this.name) return;
    const officeText = await readTextFile(`${this.stateDir}/offices/${this.name}.json`);
    this.office = officeText ? JSON.parse(officeText) : null;
    const result = await runCrew(["read", this.name, "--limit", "200", "--json"]);
    if (result.code !== 0) throw new Error(result.stderr.trim() || `crew read exited ${result.code}`);
    const posts = result.stdout.split("\n").filter(Boolean).map((line) => JSON.parse(line)).reverse();
    const fresh = this.seen ? posts.filter((post) => !this.seen.has(post.id)) : [];
    this.seen = new Set(posts.map((post) => post.id));
    this.posts = posts;
    for (const post of fresh.filter(isAlert)) {
      notify({
        title: `🏢 ${this.name}`,
        body: `${getAuthor(post)}: ${post.text}`.slice(0, 240),
        level: post.from === "crew" ? "warning" : "info",
        action: { name: "space.select", args: { id: `crew-${this.name}` } },
      });
    }
  }

  send(cx) {
    const text = this.input.value().trim();
    if (!text || !this.name || this.sending) return;
    this.sending = true;
    cx.spawn(async (cx) => {
      const result = await runCrew(["post", this.name, "--", text]).catch((error) => ({ code: 1, stderr: String(error) }));
      this.sending = false;
      this.note = result.stderr.trim() || (result.code === 0 ? null : "crew post failed");
      if (result.code === 0) {
        this.input.set_value("");
        this.draft = "";
      }
      this.reload(cx);
    });
  }

  toggle(cx) {
    const action = this.office?.state === "paused" ? "resume" : "pause";
    cx.spawn(async (cx) => {
      const result = await runCrew(["office", action, this.name]);
      this.note = result.code === 0 ? null : result.stderr.trim();
      this.reload(cx);
    });
  }

  complete(prefix, ref) {
    const next = `${this.draft.slice(0, this.draft.length - prefix.length)}${ref} `;
    this.input.set_value(next);
    this.draft = next;
    this.input.focus();
  }

  render() {
    const t = theme();
    if (!this.name) {
      return v_flex().size_full().p(20).gap(6).bg(t.surface).text_size(13)
        .child(div().text_color(t.foreground).font_semibold().child("No office running"))
        .child(div().text_color(t.dim).child("Start one: crew office start <name> --dir <project> --brief \"…\""));
    }
    return v_flex().id("crew-office").track_focus(this.handle).size_full().bg(t.surface).text_size(13)
      .child(this.renderHeader(t))
      .child(this.renderMembers(t))
      .child(this.renderComposer(t))
      .when(Boolean(this.error), (el) => el.child(div().px(16).py(6).text_size(12).text_color(t.blocked).child(this.error)))
      .child(v_flex().id("posts").flex_1().min_h(0).pb(10).overflow_y_scrollbar()
        .when(this.posts.length === 0, (el) => el.child(div().px(16).py(12).text_color(t.dim).child("No posts yet.")))
        .children(this.posts.map((post) => this.renderPost(t, post))));
  }

  renderHeader(t) {
    const office = this.office;
    const state = office?.state ?? "…";
    const isLive = state === "running" || state === "paused";
    return h_flex().h(44).flex_none().px(16).gap(10).items_center().bg(t.chrome).border_b(1).border_color(t.border)
      .child(div().text_size(15).font_semibold().text_color(t.foreground).child(`🏢 ${this.name}`))
      .child(div().px(8).py(1).rounded(9).text_size(11).font_medium().bg(t.raised).text_color(t[STATE_COLOR[state]] ?? t.dim).child(state))
      .when(Boolean(office), (el) => el.child(div().text_size(12).text_color(t.dim)
        .tooltip("Agent posts since your last post; the office pauses at the budget")
        .child(`${office.agent_posts_since_human}/${office.budget}`)))
      .when(office?.state === "paused" && Boolean(office.paused_reason), (el) => el.child(div().text_size(12).text_color(t.dim).child(office.paused_reason)))
      .child(div().flex_1())
      .when(isLive, (el) => el.child(h_flex().id("toggle").h(26).px(12).items_center().rounded(7)
        .border_1().border_color(t.input).bg(t.raised).text_size(12).text_color(t.foreground).cursor_pointer()
        .hover((s) => s.bg(t.hover))
        .on_click((_e, cx) => this.toggle(cx))
        .child(state === "paused" ? "Resume" : "Pause")));
  }

  renderMembers(t) {
    const statusByAddress = new Map(agents().map((a) => [a.address, a.status]));
    const terminalByAddress = new Map(terminals().map((x) => [x.address, x]));
    const members = Object.entries(this.office?.members ?? {});
    return h_flex().flex_none().flex_wrap().gap(6).px(14).py(8).border_b(1).border_color(t.border)
      .children(members.map(([role, address]) => {
        const terminal = terminalByAddress.get(address);
        const status = statusByAddress.get(address) ?? (terminal?.state === "live" ? terminal.status ?? "starting" : "gone");
        const look = ROLE_LOOK[role] ?? { badge: role.slice(0, 2).toUpperCase(), color: "muted" };
        return h_flex().id(`member-${role}`).h(28).pl(4).pr(10).gap(6).items_center().rounded(14).bg(t.raised)
          .cursor_pointer().hover((s) => s.bg(t.hover)).tooltip(`Peek at ${address}`)
          .on_click(() => run("terminal.peek", { terminal: address }))
          .child(this.renderBadge(t, look, 20))
          .child(div().text_size(12).text_color(t.foreground).child(role))
          .child(status === "working"
            ? h_flex().gap(4).text_size(11).text_color(t.working)
              .child(div().w(10).frames(SPIN, 90).child(SPIN[0])).child("working…")
            : div().text_size(11).text_color(t[status] ?? t.dim).child(status));
      }));
  }

  renderBadge(t, look, size) {
    return div().size(size).flex_none().rounded(size / 2).flex().items_center().justify_center()
      .bg(t[look.color] ?? t.muted).text_color(t.background).text_size(size * 0.42).font_semibold().child(look.badge);
  }

  renderComposer(t) {
    const typing = TYPING_MENTION.exec(this.draft);
    const prefix = typing?.[1] ?? "";
    const refs = typing ? [...ROLES, "team"].filter((ref) => ref.startsWith(prefix.toLowerCase())) : [];
    return v_flex().flex_none().px(14).py(10).gap(6).border_b(1).border_color(t.border)
      .child(Input.new(this.input).h(36).px(10).rounded(8).border_1().border_color(t.input).bg(t.background)
        .text_size(13).text_color(t.foreground))
      .when(refs.length > 0, (el) => el.child(h_flex().gap(4).flex_wrap().children(refs.map((ref) =>
        div().id(`ref-${ref}`).px(8).py(2).rounded(6).bg(t.raised).text_size(12).text_color(t.accent)
          .cursor_pointer().hover((s) => s.bg(t.hover))
          .on_click((_e, cx) => {
            this.complete(prefix, ref);
            cx.notify();
          })
          .child(`@${ref}`)))))
      .when(Boolean(this.note), (el) => el.child(div().text_size(11.5).text_color(t.dim).child(this.note)));
  }

  renderPost(t, post) {
    if (post.from === "crew") {
      return h_flex().id(`post-${post.id}`).px(16).py(4).gap(10).text_size(12).text_color(t.dim)
        .child(div().flex_none().child(toClock(post.at)))
        .child(div().flex_1().min_w(0).child(post.text));
    }
    const look = getLook(post);
    return h_flex().id(`post-${post.id}`).items_start().gap(10).pl(11).pr(16).py(8)
      .border_l(3).border_color(isForYou(post) ? t.accent : t.surface)
      .when(isForYou(post), (el) => el.bg(t.raised))
      .child(this.renderBadge(t, look, 28))
      .child(v_flex().flex_1().min_w(0).gap(2)
        .child(h_flex().gap(8).items_center()
          .child(div().font_semibold().text_color(t[look.color] ?? t.foreground).child(getAuthor(post)))
          .child(div().text_size(11).text_color(t.dim).child(`${post.from === "human" ? "" : `${post.from} · `}${toClock(post.at)}`)))
        .child(TextView.markdown(`md-${post.id}`, toMarkdown(post.text)).text_color(t.foreground))
        .when(Boolean(post.unresolved?.length), (el) => el.child(div().text_size(11).text_color(t.dim)
          .child(`no one matches ${post.unresolved.map((ref) => `@${ref}`).join(", ")}`))));
  }
}
