import { View, div, svg } from "gpui-kit"
import { h_flex } from "gpui-base"
import { agents, exec, focused, settings, spaces, theme } from "herdr"

const BAR_HEIGHT = 28
const DAYS = [ "Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat" ]
const MONTHS = [ "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" ]
const pad = (value) => String(value).padStart(2, "0")

function getCpuTimes (stat) {
  const values = stat.split("\n")[0].trim().split(/\s+/).slice(1).map(Number)
  return { idle: values[3] + values[4], total: values.reduce((sum, value) => sum + value, 0) }
}

function getMemoryUsage (meminfo) {
  const getKb = (key) => Number(meminfo.match(new RegExp(`^${key}:\\s+(\\d+)`, "m"))?.[1] ?? 0)
  const total = getKb("MemTotal")
  return total ? Math.round(100 * (1 - getKb("MemAvailable") / total)) : null
}

export default class MyStatus extends View {
  init (_props, cx) {
    this.cpu = null
    this.memory = null
    this.lastCpuTimes = null
    this.refresh(cx)
    cx.timer.every(3000, (cx) => this.refresh(cx))
  }

  refresh (cx) {
    cx.spawn(async (cx) => {
      const { code, stdout } = await exec("cat", [ "/proc/stat", "/proc/meminfo" ])
        .catch(() => ({ code: 1, stdout: "" }))
      if (code !== 0) return
      const cpuTimes = getCpuTimes(stdout)
      const { lastCpuTimes } = this
      if (lastCpuTimes && cpuTimes.total > lastCpuTimes.total) {
        this.cpu = Math.round(100 * (1 - (cpuTimes.idle - lastCpuTimes.idle) / (cpuTimes.total - lastCpuTimes.total)))
      }
      this.lastCpuTimes = cpuTimes
      this.memory = getMemoryUsage(stdout)
      cx.notify()
    })
  }

  render () {
    const t = theme()
    const space = spaces().find(({ id }) => id === focused()?.space)
    const agentList = agents()
    const countOf = (status) => agentList.filter((agent) => agent.status === status).length
    const now = new Date()

    const segment = ({ id, text, bg, fg, isBold = false }) => h_flex()
      .id(id)
      .h_full()
      .px(10)
      .flex_none()
      .items_center()
      .bg(bg)
      .text_color(fg)
      .when(isBold, (el) => el.font_bold())
      .child(text)
    // Powerline: the arrow takes the color it leaves and sits on the color it enters.
    const arrow = (direction, color, under) => div()
      .h_full()
      .flex_none()
      .bg(under)
      .child(svg(`mods/my-status/arrow-${direction}.svg`).w(10).h(BAR_HEIGHT).text_color(color))
    const agentCount = (status, label) => countOf(status) > 0 && div()
      .flex_none()
      .text_color(t[status])
      .child(`${label} ${countOf(status)}`)

    const leftSegments = [
      space && { id: "st-space", text: `\uf07b ${space.name}`, bg: t.accent, fg: t.accent_foreground, isBold: true },
      space?.branch && { id: "st-branch", text: `\ue725 ${space.branch}`, bg: t.raised, fg: t.foreground },
    ].filter(Boolean)
    const rightSegments = [
      this.cpu !== null && { id: "st-cpu", text: `\uf2db ${this.cpu}%`, bg: t.surface, fg: t.muted },
      this.memory !== null && { id: "st-memory", text: `\u{f035b} ${this.memory}%`, bg: t.raised, fg: t.muted },
      { id: "st-time", text: `\uf017 ${pad(now.getHours())}:${pad(now.getMinutes())}`, bg: t.selected, fg: t.foreground, isBold: true },
      { id: "st-date", text: `\uf073 ${DAYS[now.getDay()]} ${now.getDate()} ${MONTHS[now.getMonth()]}`, bg: t.accent, fg: t.accent_foreground, isBold: true },
    ].filter(Boolean)

    return h_flex()
      .id("my-status")
      .size_full()
      .items_center()
      .bg(t.chrome)
      .text_size(12)
      .font_family(settings().font_family ?? "JetBrainsMono Nerd Font")
      .children(leftSegments.flatMap((s, index) => [
        segment(s),
        arrow("right", s.bg, leftSegments[index + 1]?.bg ?? t.chrome),
      ]))
      .child(h_flex().flex_1().min_w(0).px(12).gap(14).items_center()
        .children([
          agentCount("working", "\uf110"),
          agentCount("blocked", "\uf071 needs you"),
          agentCount("done", "\uf00c done"),
        ].filter(Boolean)))
      .children(rightSegments.flatMap((s, index) => [
        arrow("left", s.bg, rightSegments[index - 1]?.bg ?? t.chrome),
        segment(s),
      ]))
  }
}
