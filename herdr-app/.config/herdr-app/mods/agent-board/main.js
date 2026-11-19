import { View, div, image, svg } from "gpui-kit"
import { v_flex, h_flex } from "gpui-base"
import { agents, terminals, run, theme, layout, props, nextCommand } from "herdr"

const STACK_ID = "main-stack"
const RANK = { blocked: 4, done: 3, working: 2, idle: 1 }
const COLUMNS = [
  { rank: 4, label: "Needs you", status: "blocked" },
  { rank: 3, label: "Done", status: "done" },
  { rank: 2, label: "Working", status: "working" },
  { rank: 1, label: "Idle", status: "idle" },
]

const toSubAgentStatus = (status) => (status === "error" ? "blocked" : status === "done" ? "idle" : status)
const toCleanTitle = (title) => (title ?? "").replace(/^[^\p{L}\p{N}]+/u, "").trim()

function getNode (node, id) {
  if (node?.id === id) return node
  for (const child of node?.children ?? []) {
    const found = getNode(child, id)
    if (found) return found
  }
  return null
}

const isBoardShown = () => getNode(layout(), STACK_ID)?.active === "board"

function toggleBoard () {
  run("layout.select", { stack: STACK_ID, child: isBoardShown() ? "main" : "board" })
}

function toDuration (ms) {
  const minutes = Math.floor(ms / 60000)
  if (minutes < 1) return "<1m"
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  return hours < 24 ? `${hours}h` : `${Math.floor(hours / 24)}d`
}

function getIcon (program, size, color) {
  if (!program?.icon) return null
  return program.tint
    ? svg(program.icon).size(size).flex_none().text_color(color)
    : image(program.icon).w(size).h(size).flex_none()
}

function getSubAgents (allTerminals, address) {
  return allTerminals
    .filter((terminal) => terminal.parent === address && terminal.state === "live")
    .flatMap((terminal) => [ terminal, ...getSubAgents(allTerminals, terminal.address) ])
}

function getCardDetail ({ tab_name, title, program }) {
  const tabName = /^\d+$/.test(tab_name) ? null : tab_name
  const cleanTitle = toCleanTitle(title)
  const parts = [ tabName, cleanTitle !== tabName && cleanTitle ].filter(Boolean)
  return parts.length ? parts.join(" · ") : program?.name ?? ""
}

export default class AgentBoard extends View {
  init (_props, cx) {
    this.isButton = props()?.role === "button"
    this.changedAt = JSON.parse(localStorage.getItem("changedAt") ?? "{}")
    cx.spawn(async () => {
      for (;;) {
        const command = await nextCommand()
        if (command === "toggle" && this.isButton) toggleBoard()
      }
    })
    if (!this.isButton) cx.timer.every(30000, (cx) => cx.notify())
  }

  track (cards, now) {
    const changed = cards.filter(({ agent, rank }) => this.changedAt[agent.address]?.rank !== rank)
    if (!changed.length) return
    for (const { agent, rank } of changed) this.changedAt[agent.address] = { rank, at: now }
    localStorage.setItem("changedAt", JSON.stringify(this.changedAt))
  }

  render () {
    const t = theme()
    return this.isButton ? this.renderButton(t) : this.renderBoard(t)
  }

  renderButton (t) {
    const isShown = isBoardShown()
    return h_flex()
      .id("board-toggle")
      .size_full()
      .px(14)
      .gap(6)
      .items_center()
      .justify_end()
      .bg(t.chrome)
      .border_t(1)
      .border_color(t.border)
      .text_size(11.8)
      .text_color(isShown ? t.foreground : t.muted)
      .cursor_pointer()
      .hover((s) => s.text_color(t.foreground))
      .tooltip(isShown ? "Back to terminals (Alt+B)" : "Agent board (Alt+B)")
      .on_click(toggleBoard)
      .child(svg("mods/workspace-chrome/layers.svg").size(13))
      .child(isShown ? "Terminals" : "Board")
  }

  renderBoard (t) {
    const allTerminals = terminals()
    const list = agents()
    const now = Date.now()
    const cards = list.map((agent) => {
      const subAgents = getSubAgents(allTerminals, agent.address)
      const subRanks = subAgents.map((terminal) => RANK[toSubAgentStatus(terminal.status)] ?? 0)
      return { agent, subAgents, rank: Math.max(RANK[agent.status] ?? 1, ...subRanks) }
    })
    this.track(cards, now)

    const chip = (terminal) => h_flex()
      .id(`chip-${terminal.address}`)
      .px(6)
      .h(20)
      .gap(5)
      .items_center()
      .rounded(5)
      .bg(t.raised)
      .text_size(11)
      .cursor_pointer()
      .hover((s) => s.bg(t.hover))
      .tooltip(`Peek at ${terminal.address}`)
      .on_click((_e, cx) => {
        cx.stop_propagation()
        run("terminal.peek", { terminal: terminal.address })
      })
      .child(div().size(6).flex_none().rounded(3).bg(t[toSubAgentStatus(terminal.status)] ?? t.dim))
      .child(div().max_w(140).truncate().text_color(t.muted)
        .child(terminal.name || terminal.template || terminal.program?.name || terminal.address))

    const card = ({ agent, subAgents }) => {
      const machine = agent.address.includes("/") ? agent.address.split("/")[0] : null
      const since = this.changedAt[agent.address]?.at
      const icon = getIcon(agent.program, 16, t.foreground)
      return v_flex()
        .id(`card-${agent.address}`)
        .flex_none()
        .p(10)
        .gap(6)
        .rounded(8)
        .bg(t.surface)
        .border_1()
        .border_color(agent.focused ? t.accent : t.border)
        .cursor_pointer()
        .hover((s) => s.bg(t.hover))
        .tooltip(`Peek at ${agent.address}`)
        .on_click(() => run("terminal.peek", { terminal: agent.address }))
        .child(h_flex().gap(8).items_center()
          .when(Boolean(icon), (el) => el.child(icon))
          .child(div().flex_1().min_w(0).truncate().font_semibold().text_color(t.foreground).child(agent.space_name || agent.address))
          .when(Boolean(machine), (el) => el.child(div().flex_none().text_size(10).text_color(t.dim).child(machine)))
          .when(agent.pinned, (el) => el.child(svg("mods/workspace-chrome/pin.svg").size(12).flex_none().text_color(t.dim)))
          .when(Boolean(since), (el) => el.child(div().flex_none().text_size(11).text_color(t.dim).child(toDuration(now - since)))))
        .child(div().truncate().text_size(12).text_color(t.muted).child(getCardDetail(agent)))
        .when(subAgents.length > 0, (el) => el.child(h_flex().flex_wrap().gap(4).children(subAgents.map(chip))))
    }

    const column = ({ rank, label, status }) => {
      const columnCards = cards
        .filter((c) => c.rank === rank)
        .sort((a, b) => b.agent.pinned - a.agent.pinned ||
          (this.changedAt[b.agent.address]?.at ?? 0) - (this.changedAt[a.agent.address]?.at ?? 0))
      return v_flex()
        .flex_1()
        .min_w(0)
        .h_full()
        .gap(8)
        .child(h_flex().px(4).gap(6).items_center().text_size(12)
          .child(div().size(7).flex_none().rounded(4).bg(t[status] ?? t.dim))
          .child(div().font_medium().text_color(columnCards.length ? t[status] ?? t.foreground : t.dim).child(label))
          .child(div().text_color(t.dim).child(String(columnCards.length))))
        .child(v_flex()
          .id(`column-${rank}`)
          .flex_1()
          .min_h(0)
          .gap(8)
          .overflow_y_scrollbar()
          .children(columnCards.map(card)))
    }

    return v_flex()
      .size_full()
      .p(12)
      .gap(12)
      .bg(t.canvas)
      .text_size(13)
      .child(h_flex().items_center().gap(8)
        .child(div().text_size(15).font_semibold().text_color(t.foreground).child("Agents"))
        .child(div().text_size(12).text_color(t.dim).child(String(list.length)))
        .child(div().flex_1())
        .child(div()
          .id("board-back")
          .px(8)
          .py(3)
          .rounded(6)
          .text_size(12)
          .text_color(t.muted)
          .cursor_pointer()
          .hover((s) => s.bg(t.hover).text_color(t.foreground))
          .on_click(toggleBoard)
          .child("Terminals · Alt+B")))
      .when(list.length === 0, (el) => el.child(div().px(4).text_size(12).text_color(t.dim).child("No agents running.")))
      .child(h_flex().flex_1().min_h(0).gap(12).children(COLUMNS.map(column)))
  }
}
