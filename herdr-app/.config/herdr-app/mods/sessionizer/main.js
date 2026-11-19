import { View, div, svg } from "gpui-kit"
import { v_flex, h_flex, InputState, Input } from "gpui-base"
import { exec, home, panes, spaces, run, theme, props, closeOverlay } from "herdr"

const MAX_ROWS = 12
const ROW_HEIGHT = 32
const MOVES = { down: 1, up: -1, "ctrl-n": 1, "ctrl-p": -1 }

function getProjectForCwd (cwd, projectPaths) {
  const owners = projectPaths.filter((path) => cwd === path || cwd.startsWith(`${path}/`))
  const [ deepest ] = owners.sort((a, b) => b.length - a.length)
  return deepest
}

function getSpaceByProject (projectPaths) {
  const spaceByTab = new Map(spaces()
    .filter((space) => space.machine === null)
    .flatMap((space) => space.tabs.map((tab) => [ tab.id, space ])))
  const entries = panes().flatMap(({ tab, cwd }) => {
    const space = spaceByTab.get(tab)
    const project = space && cwd && getProjectForCwd(cwd, projectPaths)
    return project ? [ [ project, space ] ] : []
  })
  return new Map(entries.reverse())
}

function getFuzzyScore (query, text) {
  let score = 0
  let last = -1
  for (const char of query) {
    const index = text.indexOf(char, last + 1)
    if (index === -1) return null
    if (index === last + 1) score += 3
    if (index === 0 || "/-_.".includes(text[index - 1])) score += 2
    score += 1
    last = index
  }
  return score - text.length / 100
}

export default class Sessionizer extends View {
  init (_props, cx) {
    this.projects = null
    this.error = null
    this.query = ""
    this.at = 0
    this.top = 0
    this.handle = cx.focus_handle()
    this.input = InputState.new({ placeholder: "Open a project…" })
    this.input.on("change", (_e, cx) => {
      this.query = this.input.value().toLowerCase()
      this.at = 0
      cx.notify()
    })
    this.input.on("submit", () => this.pick(this.getRows()[this.at]))
    this.input.focus()
    cx.timer.after(600, () => this.input.focus())
    cx.spawn(async (cx) => {
      const { code, stdout, stderr } = await exec("go-folder-finder", [ "list" ])
        .catch((error) => ({ code: 1, stdout: "", stderr: error.message }))
      if (code !== 0) this.error = stderr.trim() || `go-folder-finder exited ${code}`
      else this.projects = stdout.split("\n").filter(Boolean)
      cx.notify()
    })
  }

  close () {
    closeOverlay(props().overlay)
  }

  pick (row) {
    if (!row) return
    this.close()
    if (row.space) return run("space.select", { id: row.space.id })
    run("space.new", { name: row.path.split("/").at(-1), folder: row.path })
  }

  getRows () {
    if (!this.projects) return []
    const homeDir = home()
    const spaceByProject = getSpaceByProject(this.projects)
    const rows = this.projects.map((path) => ({
      path,
      label: path.startsWith(homeDir) ? `~${path.slice(homeDir.length)}` : path,
      space: spaceByProject.get(path),
    }))
    if (!this.query) return rows
    const scoredRows = rows.flatMap((row) => {
      const score = getFuzzyScore(this.query, row.label.toLowerCase())
      return score === null ? [] : [ { ...row, score } ]
    })
    return scoredRows.sort((a, b) => b.score - a.score)
  }

  render () {
    const t = theme()
    const rows = this.getRows()
    this.at = Math.max(0, Math.min(this.at, rows.length - 1))
    if (this.at < this.top) this.top = this.at
    if (this.at >= this.top + MAX_ROWS) this.top = this.at - MAX_ROWS + 1
    this.top = Math.max(0, Math.min(this.top, rows.length - MAX_ROWS))
    const shownRows = rows.slice(this.top, this.top + MAX_ROWS)

    const row = (r, index) => h_flex()
      .id(`sz-${r.path}`)
      .mx(4)
      .px(10)
      .h(ROW_HEIGHT)
      .flex_none()
      .gap(10)
      .items_center()
      .rounded(7)
      .cursor_pointer()
      .when(this.top + index === this.at, (el) => el.bg(t.hover))
      .hover((s) => s.bg(t.hover))
      .on_click(() => this.pick(r))
      .child(div().w(12).flex_none().text_color(r.space ? t.accent : t.dim).child(r.space ? "●" : "·"))
      .child(div().flex_1().min_w(0).truncate().text_color(t.foreground).child(r.label))
      .when(Boolean(r.space), (el) => el.child(div().flex_none().text_size(11).text_color(t.dim).child(r.space.name)))

    const status = this.error ?? (!this.projects ? "Loading projects…" : rows.length === 0 ? "No match" : null)

    return v_flex()
      .id("sessionizer")
      .track_focus(this.handle)
      .w_full()
      .min_h(0)
      .p(18)
      .gap(10)
      .bg(t.popover)
      .text_size(13)
      .on_key_down((e, cx) => {
        const name = e.modifiers.control ? `ctrl-${e.key}` : e.key
        if (name === "escape") return this.close()
        const move = MOVES[name]
        if (!move || rows.length === 0) return
        this.at = (this.at + move + rows.length) % rows.length
        cx.stop_propagation()
        cx.notify()
      })
      .child(h_flex().items_center()
        .child(div().flex_1().text_size(15).font_semibold().text_color(t.foreground).child("Open project"))
        .child(div().text_size(11).text_color(t.dim).child(`${rows.length} · Esc`)))
      .child(h_flex().h(36).flex_none().px(10).gap(8).items_center().rounded(9).border_1().border_color(t.accent).bg(t.background)
        .child(svg("mods/workspace-chrome/search.svg").size(15).text_color(t.dim))
        .child(Input.new(this.input).flex_1().h_full().text_size(12.8).text_color(t.foreground)))
      .when(Boolean(status), (el) => el.child(div().px(14).py(8).text_size(12).text_color(this.error ? t.blocked : t.dim).child(status)))
      .child(v_flex()
        .id("sz-list")
        .mb(6)
        .on_scroll_wheel((e, cx) => {
          const step = Math.trunc(e.delta.y / ROW_HEIGHT) || Math.sign(e.delta.y)
          this.at = Math.max(0, Math.min(this.at - step, rows.length - 1))
          cx.notify()
        })
        .children(shownRows.map(row)))
  }
}
