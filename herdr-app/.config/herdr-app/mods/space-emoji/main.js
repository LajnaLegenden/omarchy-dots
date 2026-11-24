import { View, div } from "gpui-kit"
import { spaces, run, exec, notify, appHome } from "herdr"

const CHECK_MS = 1500
const POOL = [ "🦊", "🐙", "🦉", "🐝", "🦀", "🐢", "🦄", "🐳", "🦋", "🐧" ]
const LEADING_EMOJI = /^\p{Extended_Pictographic}/u
const REPO_SCRIPT = `git -C "$1" remote get-url origin 2>/dev/null || git -C "$1" rev-parse --path-format=absolute --git-common-dir`
const WRITE_SCRIPT = `printf '%s\\n' "$1" > "$2.tmp" && mv "$2.tmp" "$2"`

const getMapPath = () => `${appHome()}/mods/space-emoji/emoji.json`

const toRepoKey = (location) => location.trim()
  .replace(/\/?\.git\/?$/, "")
  .split(/[:/]/)
  .slice(-2)
  .join("/")
  .toLowerCase()

const isCandidate = ({ machine, folder, name }) => machine === null && Boolean(folder) && !LEADING_EMOJI.test(name)

function getFreeEmoji (emojiByRepo) {
  const usedEmojis = new Set(Object.values(emojiByRepo))
  return POOL.find((emoji) => !usedEmojis.has(emoji)) ?? POOL[Object.keys(emojiByRepo).length % POOL.length]
}

async function getEmojiMap () {
  const { code, stdout } = await exec("cat", [ getMapPath() ])
  return code === 0 ? JSON.parse(stdout) : {}
}

export default class SpaceEmoji extends View {
  init (_props, cx) {
    this.repoByFolder = new Map()
    this.seenIds = new Set()
    this.lastSignature = null
    this.isSyncing = false
    cx.timer.every(CHECK_MS, (cx) => this.check(cx))
  }

  // A space must be seen twice before it counts, so a just-made one isn't pinned to a transient name.
  check (cx) {
    const currentSpaces = spaces()
    const candidates = currentSpaces.filter((space) => this.seenIds.has(space.id) && isCandidate(space))
    this.seenIds = new Set(currentSpaces.map(({ id }) => id))
    const signature = JSON.stringify(candidates.map(({ id, name, folder }) => [ id, name, folder ]))
    if (this.isSyncing || signature === this.lastSignature) return
    this.lastSignature = signature
    this.isSyncing = true
    cx.spawn(async () => {
      await this.sync(candidates)
        .catch((error) => notify({ title: "space-emoji", body: error.message, level: "error" }))
      this.isSyncing = false
    })
  }

  async getRepoKey (folder) {
    if (this.repoByFolder.has(folder)) return this.repoByFolder.get(folder)
    const { code, stdout } = await exec("sh", [ "-c", REPO_SCRIPT, "sh", folder ])
    const repo = code === 0 ? toRepoKey(stdout) : null
    this.repoByFolder.set(folder, repo)
    return repo
  }

  async sync (candidates) {
    if (!candidates.length) return
    const emojiByRepo = await getEmojiMap()
    const newEmojiByRepo = { ...emojiByRepo }
    for (const space of candidates) {
      const repo = await this.getRepoKey(space.folder)
      if (!repo) continue
      newEmojiByRepo[repo] ??= getFreeEmoji(newEmojiByRepo)
      run("space.rename", { id: space.id, name: `${newEmojiByRepo[repo]} ${space.name}` })
    }
    if (Object.keys(newEmojiByRepo).length === Object.keys(emojiByRepo).length) return
    const { code, stderr } = await exec("sh", [ "-c", WRITE_SCRIPT, "sh", JSON.stringify(newEmojiByRepo, null, 2), getMapPath() ])
    if (code !== 0) throw new Error(`emoji.json not saved: ${stderr.trim()}`)
  }

  render () {
    return div().size(0)
  }
}
