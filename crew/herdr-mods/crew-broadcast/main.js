import { View, div } from "gpui-kit"
import { v_flex, h_flex, TextareaState, Textarea } from "gpui-base"
import { agents, spaces, focused, exec, home, readTextFile, watchFolder, run, theme, props, closeOverlay } from "herdr"

const OTHER_GROUP = "Other"
const LEADING_EMOJI = /^(\p{Extended_Pictographic}\uFE0F?)\s*/u

const QUICK_PICKS = [
  [ "All", () => true ],
  [ "This repo", (row, focus) => focus.repo !== null && row.repo === focus.repo ],
  [ "This space", (row, focus) => row.spaceId === focus.spaceId ],
  [ "Working", (row) => row.status === "working" ],
  [ "Idle + done", (row) => row.status === "idle" || row.status === "done" ],
  [ "None", () => false ],
]

// exec gives up after ~30 s, so the mod sends with --reply (returns at once) and tails the replies file itself.
function execCrew (args) {
  return exec(`${home()}/.local/bin/crew`, args)
}

async function getCrewJson (args) {
  const { code, stdout, stderr } = await execCrew(args)
  if (!stdout.trim()) throw new Error(stderr.trim() || `crew exited ${code}`)
  return JSON.parse(stdout)
}

// The last piece after the final newline is empty or a reply still being written.
async function getRepliesByAddress (path) {
  const text = await readTextFile(path).catch(() => null)
  const records = (text ?? "").split("\n").slice(0, -1).flatMap((line) => {
    try {
      return [ JSON.parse(line) ]
    } catch {
      return []
    }
  })
  return new Map(records.map((record) => [ record.from, record ]))
}

// Agents on other machines reply into that machine's crew state; crew replies pulls those over hc.
async function getAllRepliesByAddress (id) {
  const { stdout } = await execCrew([ "replies", id, "--json" ])
  const records = stdout.split("\n").flatMap((line) => {
    try {
      return line ? [ JSON.parse(line) ] : []
    } catch {
      return []
    }
  })
  return new Map(records.map((record) => [ record.from, record ]))
}

// Worktrees share their origin (or main checkout) name, so every mediatool worktree space lands in one group,
// on this machine and on connected ones.
async function getRepoName ({ folder, machine }) {
  if (!folder) return null
  const git = (args) => exec("git", args, { cwd: folder, on: machine ?? null })
    .then(({ code, stdout }) => code === 0 ? stdout.trim() : "")
    .catch(() => "")
  const [ origin, commonDir ] = await Promise.all([
    git([ "remote", "get-url", "origin" ]),
    git([ "rev-parse", "--path-format=absolute", "--git-common-dir" ]),
  ])
  const originName = origin.split(/[/:]/).pop()?.replace(/\.git$/, "")
  const parts = commonDir.split("/")
  const mainName = parts.at(-1) === ".git" ? parts.at(-2) : parts.at(-1)?.replace(/\.git$/, "")
  return (originName || mainName || "").toLowerCase() || null
}

function getRepoGroups (rows, isRepoKnown) {
  const groups = new Map()
  for (const row of rows) {
    const key = row.repo ?? (isRepoKnown ? OTHER_GROUP : row.spaceName)
    const group = groups.get(key) ?? { key, emoji: null, rows: [] }
    group.emoji ??= row.spaceName.match(LEADING_EMOJI)?.[1] ?? null
    group.rows.push(row)
    groups.set(key, group)
  }
  return [ ...groups.values() ].sort((a, b) => (a.key === OTHER_GROUP) - (b.key === OTHER_GROUP))
}

function getPickerRows (crewAgents) {
  const liveByAddress = new Map(agents().map((agent) => [ agent.address, agent ]))
  const spaceIndexById = new Map(spaces().map((space) => [ space.id, space.index ]))
  const rows = crewAgents.map((agent) => {
    const live = liveByAddress.get(agent.address)
    const [ whereSpace = "", whereTab = "" ] = (agent.where ?? "").split(" / ")
    return {
      address: agent.address,
      agent: agent.agent,
      task: agent.task,
      status: live?.status ?? agent.status,
      spaceId: live?.space ?? null,
      spaceName: live?.space_name ?? whereSpace,
      tabName: live?.tab_name ?? whereTab,
      spaceIndex: spaceIndexById.get(live?.space) ?? Infinity,
    }
  })
  return rows.sort((a, b) => a.spaceIndex - b.spaceIndex || a.spaceName.localeCompare(b.spaceName))
}

const toTabLabel = (name) => /^\d+$/.test(name) ? `tab ${name}` : name
const toMachine = (address) => address.split("/")[0]
const toShortAddress = (address) => address.split("/").pop()
const toRowLabel = ({ spaceName, tabName }) => {
  const space = spaceName.replace(LEADING_EMOJI, "")
  return tabName && tabName !== "1" ? `${space} / ${toTabLabel(tabName)}` : space
}

export default class CrewBroadcast extends View {
  init (_props, cx) {
    this.phase = "compose"
    this.crewAgents = null
    this.presets = []
    this.pickedAddresses = new Set()
    this.isCollect = false
    this.hasText = false
    this.error = null
    this.result = null
    this.repliesByAddress = new Map()
    this.repoBySpaceId = null
    this.foldedRepos = new Set(JSON.parse(localStorage.getItem("foldedRepos") ?? "[]"))
    this.handle = cx.focus_handle()
    this.textarea = TextareaState.new({ placeholder: "Message for the picked agents…", rows: 5 })
    this.textarea.on("change", (_e, cx) => {
      const hasText = Boolean(this.textarea.value().trim())
      if (hasText === this.hasText) return
      this.hasText = hasText
      cx.notify()
    })
    this.textarea.on("submit", (event, cx) => {
      if (event?.secondary) this.send(cx)
    })
    this.textarea.focus()
    cx.timer.after(600, () => this.textarea.focus())
    cx.spawn(async (cx) => {
      const [ who, presets ] = await Promise.all([
        getCrewJson([ "who", "--json" ]),
        getCrewJson([ "broadcast", "--presets", "--json" ]),
      ]).catch((error) => {
        this.error = error.message
        return [ { agents: [] }, { presets: [] } ]
      })
      this.crewAgents = who.agents
      this.presets = presets.presets
      cx.notify()
    })
    cx.spawn(async (cx) => {
      const entries = await Promise.all(spaces().map(async (space) => [ space.id, await getRepoName(space) ]))
      this.repoBySpaceId = new Map(entries)
      cx.notify()
    })
  }

  toggleFold (key) {
    if (this.foldedRepos.has(key)) this.foldedRepos.delete(key)
    else this.foldedRepos.add(key)
    localStorage.setItem("foldedRepos", JSON.stringify([ ...this.foldedRepos ]))
  }

  close () {
    closeOverlay(props().overlay)
  }

  focusAgent (address) {
    this.close()
    run("agent.focus", { terminal: address })
  }

  send (cx) {
    const text = this.textarea.value().trim()
    const addresses = getPickerRows(this.crewAgents ?? [])
      .map(({ address }) => address)
      .filter((address) => this.pickedAddresses.has(address))
    if (this.phase !== "compose" || !text || !addresses.length) return
    const args = [ "broadcast", "--to", addresses.join(","), "--json", ...(this.isCollect ? [ "--reply" ] : []), "--", text ]
    this.phase = "sending"
    this.error = null
    cx.notify()
    cx.spawn(async (cx) => {
      this.result = await getCrewJson(args).catch((error) => {
        this.error = error.message
        return null
      })
      this.phase = this.result ? "results" : "compose"
      cx.notify()
      if (this.result?.replies_path) await this.watchReplies(this.result.replies_path, cx)
    })
  }

  async watchReplies (path, cx) {
    const folder = path.slice(0, path.lastIndexOf("/"))
    const { id, targets } = this.result
    const hasRemote = targets.some(({ address, delivery }) => delivery === "sent" && address.includes("/"))
    const refresh = async (cx) => {
      this.repliesByAddress = hasRemote
        ? await getAllRepliesByAddress(id).catch(() => this.repliesByAddress)
        : await getRepliesByAddress(path)
      cx.notify()
    }
    await exec("mkdir", [ "-p", folder ]).catch(() => null)
    await refresh(cx)
    if (hasRemote) cx.timer.every(3000, (cx) => refresh(cx))
    try {
      for (;;) {
        await watchFolder(folder)
        await refresh(cx)
      }
    } catch {
      cx.timer.every(2000, (cx) => refresh(cx))
    }
  }

  renderCompose (t) {
    const repoBySpaceId = this.repoBySpaceId
    const rows = getPickerRows(this.crewAgents ?? []).map((row) => ({ ...row, repo: repoBySpaceId?.get(row.spaceId) ?? null }))
    const spaceId = focused()?.space
    const focus = { spaceId, repo: repoBySpaceId?.get(spaceId) ?? null }
    const pickedCount = rows.filter(({ address }) => this.pickedAddresses.has(address)).length
    const canSend = this.phase === "compose" && this.hasText && pickedCount > 0

    const chip = (id, label, onClick) => div()
      .id(id)
      .h(24)
      .px(9)
      .flex()
      .flex_none()
      .items_center()
      .rounded(6)
      .border_1()
      .border_color(t.border)
      .bg(t.raised)
      .text_size(12)
      .text_color(t.foreground)
      .cursor_pointer()
      .hover((s) => s.bg(t.hover))
      .on_click(onClick)
      .child(label)

    const checkbox = (isTicked) => div()
      .flex_none()
      .size(14)
      .rounded(4)
      .border_1()
      .border_color(isTicked ? t.foreground : t.border)
      .flex()
      .items_center()
      .justify_center()
      .text_size(10)
      .text_color(t.foreground)
      .child(isTicked === "partial" ? "–" : isTicked ? "✓" : "")

    const presetChip = (preset) => chip(`cb-preset-${preset.name}`, preset.name, (_e, cx) => {
      this.textarea.set_value(preset.text)
      this.hasText = true
      this.isCollect = preset.collect
      cx.notify()
    }).tooltip(preset.text)

    const quickChip = ([ label, isPicked ]) => chip(`cb-pick-${label}`, label, (_e, cx) => {
      this.pickedAddresses = new Set(rows.filter((row) => isPicked(row, focus)).map(({ address }) => address))
      cx.notify()
    })

    const machineBadge = (machine) => div()
      .flex_none()
      .px(6)
      .rounded(5)
      .bg(t.raised)
      .text_size(10.5)
      .text_color(t.muted)
      .child(machine)

    const groupHeader = (group) => {
      const pickedInGroup = group.rows.filter(({ address }) => this.pickedAddresses.has(address)).length
      const tickState = pickedInGroup === 0 ? false : pickedInGroup === group.rows.length ? true : "partial"
      const workingCount = group.rows.filter(({ status }) => status === "working").length
      const isFolded = this.foldedRepos.has(group.key)
      const summary = [
        `${group.rows.length} agent${group.rows.length === 1 ? "" : "s"}`,
        workingCount > 0 && `${workingCount} working`,
        isFolded && pickedInGroup > 0 && `${pickedInGroup} picked`,
      ].filter(Boolean).join(" · ")
      return h_flex()
        .h(30)
        .mt(4)
        .gap(6)
        .flex_none()
        .items_center()
        .child(div()
          .id(`cb-fold-${group.key}`)
          .w(18)
          .flex_none()
          .text_center()
          .text_size(11)
          .text_color(t.dim)
          .cursor_pointer()
          .hover((s) => s.text_color(t.foreground))
          .on_click((_e, cx) => {
            this.toggleFold(group.key)
            cx.notify()
          })
          .child(isFolded ? "▸" : "▾"))
        .child(h_flex()
          .id(`cb-group-${group.key}`)
          .flex_1()
          .min_w(0)
          .h(28)
          .px(6)
          .gap(8)
          .items_center()
          .rounded(7)
          .cursor_pointer()
          .hover((s) => s.bg(t.hover))
          .on_click((_e, cx) => {
            const addresses = group.rows.map(({ address }) => address)
            for (const address of addresses) {
              if (tickState === true) this.pickedAddresses.delete(address)
              else this.pickedAddresses.add(address)
            }
            cx.notify()
          })
          .child(checkbox(tickState))
          .when(Boolean(group.emoji), (el) => el.child(div().flex_none().child(group.emoji)))
          .child(div().flex_1().min_w(0).truncate().font_semibold().text_color(t.foreground).child(group.key))
          .child(div().flex_none().text_size(11.5).text_color(t.dim).child(summary)))
    }

    const row = (r) => h_flex()
      .id(`cb-row-${r.address}`)
      .h(28)
      .px(8)
      .gap(9)
      .flex_none()
      .items_center()
      .rounded(7)
      .cursor_pointer()
      .hover((s) => s.bg(t.hover))
      .on_click((_e, cx) => {
        if (this.pickedAddresses.has(r.address)) this.pickedAddresses.delete(r.address)
        else this.pickedAddresses.add(r.address)
        cx.notify()
      })
      .ml(24)
      .child(checkbox(this.pickedAddresses.has(r.address)))
      .child(div().size(7).flex_none().rounded(4).bg(t[r.status] ?? t.unknown))
      .child(div().w(150).flex_none().truncate().text_color(t.foreground).child(toRowLabel(r)))
      .child(div().w(34).flex_none().text_size(12).text_color(t.dim).child(toShortAddress(r.address)))
      .child(div().w(76).flex_none().truncate().text_size(11.5).text_color(t.dim).child(r.agent ?? ""))
      .child(div().flex_1().min_w(0).truncate().text_size(12).text_color(t.muted).child(r.task ?? ""))
      .when(r.address.includes("/"), (el) => el.child(machineBadge(toMachine(r.address))))

    const list = getRepoGroups(rows, repoBySpaceId !== null).flatMap((group) => [
      groupHeader(group),
      ...(this.foldedRepos.has(group.key) ? [] : group.rows.map(row)),
    ])
    const emptyText = this.crewAgents === null ? "Loading agents…" : "No agents running."
    const sendLabel = this.phase === "sending" ? "Sending…" : `Send to ${pickedCount} · Ctrl+Enter`

    return [
      h_flex().gap(6).items_center().flex_wrap()
        .child(div().w(56).flex_none().text_size(12).text_color(t.dim).child("Presets"))
        .children(this.presets.map(presetChip)),
      div().flex_none().p(8).rounded(9).border_1().border_color(t.input).bg(t.background)
        .child(Textarea.new(this.textarea).w_full().text_size(13).text_color(t.foreground)),
      h_flex()
        .id("cb-collect")
        .gap(8)
        .items_center()
        .cursor_pointer()
        .text_size(12.5)
        .text_color(t.muted)
        .on_click((_e, cx) => {
          this.isCollect = !this.isCollect
          cx.notify()
        })
        .child(checkbox(this.isCollect))
        .child("Collect replies"),
      h_flex().gap(6).items_center()
        .child(div().w(56).flex_none().text_size(12).text_color(t.dim).child("Targets"))
        .children(QUICK_PICKS.map(quickChip))
        .child(div().flex_1())
        .child(div().text_size(11.5).text_color(t.dim).child(`${pickedCount} of ${rows.length}`)),
      v_flex()
        .id("cb-targets")
        .flex_1()
        .min_h(0)
        .overflow_y_scrollbar()
        .when(!rows.length, (el) => el.child(div().px(8).py(6).text_size(12).text_color(t.dim).child(emptyText)))
        .children(list),
      h_flex().gap(10).items_center()
        .child(div().flex_1().min_w(0).truncate().text_size(12).text_color(t.blocked).child(this.error ?? ""))
        .child(h_flex()
          .id("cb-send")
          .h(32)
          .px(14)
          .flex_none()
          .items_center()
          .rounded(8)
          .bg(canSend ? t.solid : t.raised)
          .text_size(12.5)
          .text_color(canSend ? t.solid_foreground : t.dim)
          .when(canSend, (el) => el.cursor_pointer().hover((s) => s.opacity(0.88)).on_click((_e, cx) => this.send(cx)))
          .child(sendLabel)),
    ]
  }

  renderResults (t) {
    const { id, text, reply, targets, summary } = this.result
    const liveByAddress = new Map(agents().map((agent) => [ agent.address, agent ]))
    const repliedCount = targets.filter(({ address }) => this.repliesByAddress.has(address)).length
    const counts = [
      `${summary.sent} sent`,
      summary.skipped > 0 && `${summary.skipped} skipped`,
      summary.failed > 0 && `${summary.failed} failed`,
      reply && `${repliedCount}/${summary.sent} replied`,
    ].filter(Boolean).join(" · ")

    const getDeliveryLabel = ({ address, delivery, reason }) => {
      if (this.repliesByAddress.has(address)) return [ "replied", t.done ]
      if (delivery === "sent") return [ reply ? "waiting" : "sent", t.dim ]
      return [ reason ? `${delivery} (${reason})` : delivery, t.blocked ]
    }

    const row = (target) => {
      const status = liveByAddress.get(target.address)?.status ?? target.status
      const replyRecord = this.repliesByAddress.get(target.address)
      const [ label, labelColor ] = getDeliveryLabel(target)
      return v_flex()
        .id(`cb-result-${target.address}`)
        .flex_none()
        .px(8)
        .py(6)
        .gap(3)
        .rounded(7)
        .when(target.agent !== null, (el) => el
          .cursor_pointer()
          .hover((s) => s.bg(t.hover))
          .tooltip(`Go to ${target.address}`)
          .on_click(() => this.focusAgent(target.address)))
        .child(h_flex().gap(9).items_center()
          .child(div().size(7).flex_none().rounded(4).bg(t[status] ?? t.unknown))
          .child(div().w(34).flex_none().text_size(12).text_color(t.dim).child(toShortAddress(target.address)))
          .child(div().flex_1().min_w(0).truncate().text_color(t.foreground).child(target.where ?? "not running"))
          .when(target.address.includes("/"), (el) => el.child(div().flex_none().px(6).rounded(5).bg(t.raised)
            .text_size(10.5).text_color(t.muted).child(toMachine(target.address))))
          .child(div().flex_none().text_size(11.5).text_color(t.dim).child(target.agent ?? ""))
          .child(div().flex_none().text_size(11.5).text_color(labelColor).child(label)))
        .when(Boolean(replyRecord), (el) => el.child(div().pl(50).text_size(12.5).text_color(t.foreground).child(replyRecord.text)))
    }

    const hint = reply ? `Click an agent to go to it · later: crew replies ${id}` : "Click an agent to go to it"

    return [
      div().truncate().text_size(12.5).text_color(t.muted).child(text),
      div().text_size(12).text_color(t.dim).child(counts),
      v_flex()
        .id("cb-results")
        .flex_1()
        .min_h(0)
        .overflow_y_scrollbar()
        .children(targets.map(row)),
      div().text_size(11.5).text_color(t.dim).child(hint),
    ]
  }

  render () {
    const t = theme()
    const isResults = this.phase === "results"
    return v_flex()
      .id("crew-broadcast")
      .track_focus(this.handle)
      .size_full()
      .min_h(0)
      .p(18)
      .gap(12)
      .bg(t.popover)
      .text_size(13)
      .on_key_down((e, cx) => {
        if (e.key === "escape") return this.close()
        if (e.key !== "enter" || !(e.modifiers.control || e.modifiers.platform)) return
        cx.stop_propagation()
        this.send(cx)
      })
      .child(h_flex().items_center()
        .child(div().flex_1().text_size(15).font_semibold().text_color(t.foreground)
          .child(isResults ? `Broadcast ${this.result.id}` : "Broadcast"))
        .child(div().text_size(11).text_color(t.dim).child("Esc")))
      .children(isResults ? this.renderResults(t) : this.renderCompose(t))
  }
}
