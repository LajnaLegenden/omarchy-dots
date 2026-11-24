import { View, div, svg } from "gpui-kit"
import { v_flex, h_flex } from "gpui-base"
import { exec, panes, spaces, focused, run, theme, notify, nextCommand, layout } from "herdr"

const FAST_POLL_MS = 30_000
const SLOW_POLL_MS = 120_000
const STUCK_MS = 60 * 60_000
const RUNNING = [ "PENDING", "EXPECTED" ]
const FAILING = [ "FAILURE", "ERROR" ]
const ATTENTION_URGENCY = 3
const MIN_CHROMA = 48
const stateMap = {
  changes: { urgency: 6, label: "Changes requested", color: "ansi3", fallback: "#f59e0b", glyph: "●" },
  failing: { urgency: 5, label: "CI failing", color: "ansi1", fallback: "#ef4444", glyph: "✕" },
  stuck: { urgency: 4, label: "CI stuck", color: "ansi5", fallback: "#f97316", glyph: "!" },
  running: { urgency: 3, label: "CI running", color: "ansi4", fallback: "#3b82f6", glyph: null },
  approved: { urgency: 2, label: "Approved", color: "ansi2", fallback: "#22c55e", glyph: "✓" },
  review: { urgency: 1, label: "Review", color: "ansi8", fallback: "#64748b", glyph: "○" },
}
const PR_QUERY = `query {
  viewer { login }
  search(query: "is:pr is:open author:@me archived:false", type: ISSUE, first: 100) {
    nodes { ... on PullRequest {
      id number title url isDraft updatedAt headRefName reviewDecision
      repository { nameWithOwner }
      reviews(last: 10) { nodes { id state author { __typename login } } }
      commits(last: 1) { nodes { commit {
        committedDate
        statusCheckRollup { state contexts(first: 100) { nodes {
          __typename
          ... on StatusContext { state createdAt }
          ... on CheckRun { status startedAt }
        } } }
      } } }
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

const toTint = (color, alpha) => `${color.slice(0, 7)}${Math.round(alpha * 255).toString(16).padStart(2, "0")}`

const toRgb = (color) => [ 1, 3, 5 ].map((start) => parseInt(color.slice(start, start + 2), 16))

function getContrastText (color) {
  const [ r, g, b ] = toRgb(color)
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#000000" : "#ffffff"
}

function getStateColor (t, { color, fallback }) {
  const [ r, g, b ] = toRgb(t[color])
  return Math.max(r, g, b) - Math.min(r, g, b) >= MIN_CHROMA ? t[color] : fallback
}

function toAge (iso, now) {
  const minutes = Math.floor((now - Date.parse(iso)) / 60_000)
  if (minutes < 60) return `${Math.max(minutes, 1)}m`
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h`
  if (minutes < 43_200) return `${Math.floor(minutes / 1440)}d`
  return `${Math.floor(minutes / 43_200)}mo`
}

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

// An EXPECTED required check that never reported has no context, so the head commit time stands in.
function getPendingSince ({ committedDate, statusCheckRollup }) {
  const startTimes = statusCheckRollup.contexts.nodes.flatMap((context) => {
    const isPending = context.__typename === "CheckRun" ? context.status !== "COMPLETED" : RUNNING.includes(context.state)
    const startedAt = context.startedAt ?? context.createdAt
    return isPending && startedAt ? [ Date.parse(startedAt) ] : []
  })
  return startTimes.length ? Math.min(...startTimes) : Date.parse(committedDate)
}

const isBot = (author) => author.__typename === "Bot" || author.login.endsWith("[bot]")

function getStateKey ({ review, isFailing, isStuck, isRunning }) {
  if (review === "CHANGES_REQUESTED") return "changes"
  if (isFailing) return "failing"
  if (isStuck) return "stuck"
  if (isRunning) return "running"
  if (review === "APPROVED") return "approved"
  return "review"
}

async function getMyPrs () {
  const stdout = await getStdout("gh", [ "api", "graphql", "-f", `query=${PR_QUERY}` ])
  const { viewer, search } = JSON.parse(stdout).data
  const now = Date.now()
  return search.nodes.map((node) => {
    const commit = node.commits.nodes[0]?.commit
    const ci = commit?.statusCheckRollup?.state ?? null
    const isRunning = RUNNING.includes(ci)
    const latestReview = node.reviews.nodes
      .filter(({ author }) => author && author.login !== viewer.login && !isBot(author))
      .at(-1) ?? null
    const pr = {
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
      isFailing: FAILING.includes(ci),
      isRunning,
      isStuck: isRunning && now - getPendingSince(commit) > STUCK_MS,
      latestReview,
    }
    return { ...pr, state: getStateKey(pr) }
  })
}

function getToasts (pr, previous) {
  if (!previous || pr.isDraft) return []
  const { latestReview } = pr
  const isNewComment = latestReview?.state === "COMMENTED" && latestReview.id !== previous.latestReview?.id
  return [
    pr.review === "CHANGES_REQUESTED" && previous.review !== "CHANGES_REQUESTED" && { title: "Changes requested", level: "warning" },
    pr.review === "APPROVED" && previous.review !== "APPROVED" && { title: "Approved", level: "success" },
    pr.isFailing && !previous.isFailing && { title: "CI failed", level: "error" },
    pr.isStuck && !previous.isStuck && { title: "CI stuck", level: "warning" },
    pr.ci === "SUCCESS" && previous.isRunning && { title: "CI passed", level: "success" },
    isNewComment && { title: `Review comment from ${latestReview.author.login}`, level: "info" },
  ].filter(Boolean)
}

const getUrgency = (pr) => stateMap[pr.state].urgency

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
        .then(() => this.prs.some((pr) => pr.isRunning && !pr.isStuck))
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
    for (const pr of this.previousByKey ? scopedPrs : []) {
      for (const toast of getToasts(pr, this.previousByKey.get(pr.key))) {
        notify({ ...toast, body: `${pr.repoName}#${pr.number} ${pr.title}`, action: { name: `my-prs.open-${pr.id}` } })
      }
    }
    this.previousByKey = new Map(scopedPrs.map((pr) => [ pr.key, pr ]))
    this.urlById = new Map(scopedPrs.map((pr) => [ pr.id, pr.url ]))
    this.checkouts = checkouts
    this.projectPaths = [ ...new Set([ ...projects, ...checkouts.map(({ path }) => path) ]) ]
    this.error = null
    this.prs = scopedPrs.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
  }

  glyph (t, pr) {
    const state = stateMap[pr.state]
    const color = getStateColor(t, state)
    if (!state.glyph) return svg("mods/workspace-chrome/spinner.svg").size(12).text_color(color).spin(900)
    return div().text_color(color).child(state.glyph)
  }

  render () {
    const t = theme()
    const now = Date.now()
    const isCollapsed = isNarrow()
    const focusedRepo = getFocusedRepo(this.checkouts)
    const prs = (this.prs ?? []).filter((pr) =>
      focusedRepo ? pr.repo === focusedRepo : getUrgency(pr) >= ATTENTION_URGENCY)
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

    const spaceButton = (pr, checkout) => div()
      .id(`pr-space-${pr.id}`)
      .flex_none()
      .p(2)
      .rounded(4)
      .text_color(t.dim)
      .hover((s) => s.bg(t.raised).text_color(t.foreground))
      .tooltip(`Open space: ${checkout.path}`)
      .on_click((_e, cx) => {
        cx.stop_propagation()
        openProject(checkout.path, this.projectPaths)
      })
      .child(svg("mods/workspace-chrome/terminal.svg").size(13))

    const card = (pr) => {
      const state = stateMap[pr.state]
      const color = getStateColor(t, state)
      const checkout = this.checkouts.find(({ repo, branch }) => repo === pr.repo && branch === pr.branch)
      const pill = h_flex()
        .flex_none()
        .h(17)
        .px(6)
        .items_center()
        .rounded(8)
        .bg(color)
        .text_size(10.5)
        .font_medium()
        .text_color(getContrastText(color))
        .child(state.label)
      return v_flex()
        .id(`pr-${pr.id}`)
        .flex_none()
        .px(10)
        .py(6)
        .gap(3)
        .rounded(8)
        .border_l(3)
        .border_color(color)
        .bg(toTint(color, pr.isDraft ? 0.06 : 0.14))
        .cursor_pointer()
        .hover((s) => s.bg(toTint(color, 0.24)))
        .tooltip(`${pr.repoName}#${pr.number} ${pr.title}`)
        .on_click(() => openPr(pr))
        .child(h_flex()
          .gap(6)
          .items_center()
          .child(div().flex_none().text_size(12).font_medium().text_color(t.muted)
            .child(focusedRepo ? `#${pr.number}` : `${pr.repoName}#${pr.number}`))
          .child(pill)
          .when(pr.isDraft, (el) => el.child(div().flex_none().text_size(11).text_color(t.dim).child("draft")))
          .child(div().flex_1())
          .when(Boolean(checkout), (el) => el.child(spaceButton(pr, checkout)))
          .child(div().flex_none().text_size(11).text_color(t.dim).child(toAge(pr.updatedAt, now))))
        .child(div().min_w(0).truncate().text_color(pr.isDraft ? t.muted : t.foreground).child(toShortTitle(pr.title)))
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

    const doneText = focusedRepo ? "No open pull requests." : "Nothing failing, running or waiting on you."
    const emptyText = !this.prs ? "Loading…" : doneText

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
        .pb(isCollapsed ? 0 : 8)
        .gap(isCollapsed ? 0 : 6)
        .overflow_y_scrollbar()
        .children(prs.map(isCollapsed ? compactRow : card)))
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
