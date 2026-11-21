import { View, div, svg } from "gpui-kit"
import { v_flex, h_flex } from "gpui-base"
import { exec, panes, spaces, focused, run, theme, notify, nextCommand, layout } from "herdr"

const FAST_POLL_MS = 30_000
const SLOW_POLL_MS = 120_000
const RUNNING = [ "PENDING", "EXPECTED" ]
const FAILING = [ "FAILURE", "ERROR" ]
const GROUPS = [
  { urgency: 3, label: "Changes requested", color: "ansi3" },
  { urgency: 2, label: "CI failing", color: "ansi1" },
  { urgency: 1, label: "CI running", color: "working" },
]
const PR_QUERY = `query {
  search(query: "is:pr is:open author:@me archived:false", type: ISSUE, first: 100) {
    nodes { ... on PullRequest {
      id number title url isDraft updatedAt headRefName reviewDecision
      repository { nameWithOwner }
      commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
    } }
  }
}`
const CHECKOUTS_SCRIPT = `for p; do
  o=$(git -C "$p" remote get-url origin 2>/dev/null) || continue
  git -C "$p" worktree list --porcelain | awk -v o="$o" '/^worktree /{w=substr($0,10)} /^branch /{print o "\\t" w "\\t" substr($0,19)}'
done | sort -u`

async function getStdout (command, args) {
  const { code, stdout, stderr } = await exec(command, args)
  if (code !== 0) throw new Error(stderr.trim() || `${command} exited ${code}`)
  return stdout
}

const toRepoSlug = (remote) => remote.match(/github\.com[:/](.+?)(?:\.git)?\/?$/)?.[1]?.toLowerCase()

function getNode (node, id) {
  if (node?.id === id) return node
  for (const child of node?.children ?? []) {
    const found = getNode(child, id)
    if (found) return found
  }
  return null
}

const isNarrow = () => (getNode(layout(), "sidebar")?.size?.px ?? Infinity) < 160

function getProjectForCwd (cwd, projectPaths) {
  const owners = projectPaths.filter((path) => cwd === path || cwd.startsWith(`${path}/`))
  const [ deepest ] = owners.sort((a, b) => b.length - a.length)
  return deepest
}

function openProject (path, projectPaths) {
  const spaceByTab = new Map(spaces()
    .filter((space) => space.machine === null)
    .flatMap((space) => space.tabs.map((tab) => [ tab.id, space ])))
  const match = panes().find(({ tab, cwd }) =>
    spaceByTab.has(tab) && cwd && getProjectForCwd(cwd, projectPaths) === path)
  if (match) return run("space.select", { id: spaceByTab.get(match.tab).id })
  run("space.new", { name: path.split("/").at(-1), folder: path })
}

function getFocusedRepo (checkouts) {
  const space = spaces().find(({ id }) => id === focused()?.space)
  if (!space?.folder || space.machine !== null) return null
  const owner = getProjectForCwd(space.folder, checkouts.map(({ path }) => path))
  return checkouts.find(({ path }) => path === owner)?.repo ?? null
}

const toShortTitle = (title) => title
  .replace(/^[\w-]+(\([^)]*\))?!?:\s*/, "")
  .replace(/^[\w.-]+\/(?=\S)/, "")

async function getCheckouts () {
  const projects = (await getStdout("go-folder-finder", [ "list" ])).split("\n").filter(Boolean)
  const rawCheckouts = await getStdout("sh", [ "-c", CHECKOUTS_SCRIPT, "sh", ...projects ])
  const checkouts = rawCheckouts.split("\n").filter(Boolean).flatMap((line) => {
    const [ remote, path, branch ] = line.split("\t")
    const repo = toRepoSlug(remote)
    return repo ? [ { repo, path, branch } ] : []
  })
  return { projects, checkouts }
}

async function getMyPrs () {
  const stdout = await getStdout("gh", [ "api", "graphql", "-f", `query=${PR_QUERY}` ])
  return JSON.parse(stdout).data.search.nodes.map((node) => {
    const ci = node.commits.nodes[0]?.commit.statusCheckRollup?.state ?? null
    return {
      id: node.id,
      key: `${node.repository.nameWithOwner}#${node.number}`,
      repo: node.repository.nameWithOwner.toLowerCase(),
      repoName: node.repository.nameWithOwner.split("/")[1],
      number: node.number,
      title: node.title,
      url: node.url,
      isDraft: node.isDraft,
      updatedAt: node.updatedAt,
      branch: node.headRefName,
      review: node.reviewDecision,
      ci,
      hasChanges: node.reviewDecision === "CHANGES_REQUESTED",
      isFailing: FAILING.includes(ci),
      isRunning: RUNNING.includes(ci),
    }
  })
}

function getToast (pr, previous) {
  if (!previous || pr.isDraft) return null
  if (pr.hasChanges && !previous.hasChanges) return { title: "Changes requested", level: "warning" }
  if (pr.isFailing && !previous.isFailing) return { title: "CI failed", level: "error" }
  if (pr.ci === "SUCCESS" && previous.isRunning) return { title: "CI passed", level: "success" }
  return null
}

const getUrgency = (pr) => (pr.hasChanges ? 3 : pr.isFailing ? 2 : 1)

export default class MyPrs extends View {
  init (_props, cx) {
    this.prs = null
    this.checkouts = []
    this.projectPaths = []
    this.previousByKey = null
    this.urlById = new Map()
    this.error = null
    this.isFetching = false
    this.pollToken = 0
    this.refresh(cx)
    cx.spawn(async (cx) => {
      for (;;) {
        const command = await nextCommand()
        if (command === "refresh") this.refresh(cx)
        else if (this.urlById.has(command.replace(/^open-/, ""))) exec("xdg-open", [ this.urlById.get(command.replace(/^open-/, "")) ])
      }
    })
  }

  refresh (cx) {
    if (this.isFetching) return
    this.isFetching = true
    cx.notify()
    cx.spawn(async (cx) => {
      const isRunning = await this.load()
        .then(() => this.prs.some((pr) => pr.isRunning))
        .catch((error) => {
          this.error = error.message
          return false
        })
      this.isFetching = false
      const token = ++this.pollToken
      cx.timer.after(isRunning ? FAST_POLL_MS : SLOW_POLL_MS, (cx) => {
        if (token === this.pollToken) this.refresh(cx)
      })
      cx.notify()
    })
  }

  async load () {
    const [ { projects, checkouts }, allPrs ] = await Promise.all([ getCheckouts(), getMyPrs() ])
    const localRepos = new Set(checkouts.map(({ repo }) => repo))
    const scopedPrs = allPrs.filter((pr) => localRepos.has(pr.repo))
    if (this.previousByKey) {
      for (const pr of scopedPrs) {
        const toast = getToast(pr, this.previousByKey.get(pr.key))
        if (toast) notify({ ...toast, body: `${pr.repoName}#${pr.number} ${pr.title}`, action: { name: `my-prs.open-${pr.id}` } })
      }
    }
    this.previousByKey = new Map(scopedPrs.map((pr) => [ pr.key, pr ]))
    this.urlById = new Map(scopedPrs.map((pr) => [ pr.id, pr.url ]))
    this.checkouts = checkouts
    this.projectPaths = [ ...new Set([ ...projects, ...checkouts.map(({ path }) => path) ]) ]
    this.error = null
    this.prs = scopedPrs.filter((pr) => pr.hasChanges || pr.isFailing || pr.isRunning).sort((a, b) =>
      getUrgency(b) - getUrgency(a) || a.isDraft - b.isDraft || b.updatedAt.localeCompare(a.updatedAt))
  }

  glyph (t, pr) {
    if (pr.isFailing) return div().text_color(t.ansi1).child("✕")
    if (pr.hasChanges) return div().text_color(t.ansi3).child("●")
    return svg("mods/workspace-chrome/spinner.svg").size(12).text_color(t.working).spin(900)
  }

  render () {
    const t = theme()
    const isCollapsed = isNarrow()
    const focusedRepo = getFocusedRepo(this.checkouts)
    const prs = (this.prs ?? []).filter((pr) => !focusedRepo || pr.repo === focusedRepo)
    const openPr = (pr) => exec("xdg-open", [ pr.url ])

    const compactRow = (pr) => h_flex()
      .id(`pr-${pr.id}`)
      .h(26)
      .flex_none()
      .justify_center()
      .items_center()
      .cursor_pointer()
      .hover((s) => s.bg(t.hover))
      .tooltip(`${pr.repoName}#${pr.number} ${pr.title}`)
      .on_click(() => openPr(pr))
      .child(this.glyph(t, pr))

    const groupHeader = ({ label, color }, count) => h_flex()
      .id(`pr-group-${label}`)
      .px(8)
      .pt(8)
      .h(30)
      .flex_none()
      .gap(6)
      .items_center()
      .text_size(11)
      .font_medium()
      .child(div().text_color(t[color]).child(label))
      .child(div().text_color(t.dim).child(String(count)))

    const row = (pr) => {
      const checkout = this.checkouts.find(({ repo, branch }) => repo === pr.repo && branch === pr.branch)
      return h_flex()
        .id(`pr-${pr.id}`)
        .px(8)
        .h(28)
        .flex_none()
        .rounded(8)
        .gap(6)
        .items_center()
        .cursor_pointer()
        .hover((s) => s.bg(t.hover))
        .tooltip(`${pr.repoName}#${pr.number} ${pr.title}`)
        .on_click(() => openPr(pr))
        .child(div().flex_none().text_color(t.dim).child(focusedRepo ? `#${pr.number}` : `${pr.repoName}#${pr.number}`))
        .child(div().flex_1().min_w(0).truncate().text_color(pr.isDraft ? t.muted : t.foreground).child(toShortTitle(pr.title)))
        .when(pr.isDraft, (el) => el.child(div().flex_none().text_size(11).text_color(t.dim).child("draft")))
        .when(Boolean(checkout), (el) => el.child(div()
          .id(`pr-space-${pr.id}`)
          .flex_none()
          .p(3)
          .rounded(4)
          .text_color(t.dim)
          .hover((s) => s.bg(t.raised).text_color(t.foreground))
          .tooltip(`Open space: ${checkout?.path}`)
          .on_click((_e, cx) => {
            cx.stop_propagation()
            openProject(checkout.path, this.projectPaths)
          })
          .child(svg("mods/workspace-chrome/terminal.svg").size(13))))
    }

    const refreshButton = div()
      .id("pr-refresh")
      .text_size(12)
      .text_color(t.dim)
      .cursor_pointer()
      .hover((s) => s.text_color(t.foreground))
      .tooltip("Refresh now")
      .on_click((_e, cx) => this.refresh(cx))
      .child(this.isFetching
        ? svg("mods/workspace-chrome/spinner.svg").size(12).spin(900)
        : div().child("↻"))

    const emptyText = !this.prs ? "Loading…" : "Nothing failing, running or waiting on you."

    return v_flex()
      .size_full()
      .min_h(0)
      .bg(t.chrome)
      .border_t(1)
      .border_color(t.border)
      .text_size(13)
      .when(!isCollapsed, (el) => el.child(h_flex()
        .px(16)
        .h(41)
        .pt(14)
        .pb(5)
        .flex_none()
        .gap(6)
        .items_center()
        .child(div().text_size(11.5).font_medium().text_color(t.dim)
          .child(focusedRepo ? `Pull requests · ${focusedRepo.split("/")[1]}` : "Pull requests"))
        .when(prs.length > 0, (el) => el.child(div().text_size(11).text_color(t.dim).child(String(prs.length))))
        .child(div().flex_1())
        .child(refreshButton)))
      .when(!isCollapsed && prs.length === 0, (el) => el.child(div().px(16).text_size(12).text_color(t.dim).child(emptyText)))
      .child(v_flex()
        .id("pr-list")
        .flex_1()
        .min_h(0)
        .px(isCollapsed ? 0 : 8)
        .overflow_y_scrollbar()
        .children(isCollapsed ? prs.map(compactRow) : GROUPS.flatMap((group) => {
          const members = prs.filter((pr) => getUrgency(pr) === group.urgency)
          return members.length ? [ groupHeader(group, members.length), ...members.map(row) ] : []
        })))
      .when(Boolean(this.error) && !isCollapsed, (el) => el.child(div()
        .id("pr-error")
        .px(16)
        .py(6)
        .flex_none()
        .truncate()
        .text_size(11)
        .text_color(t.blocked)
        .tooltip(this.error ?? "")
        .child(this.error ?? "")))
  }
}
