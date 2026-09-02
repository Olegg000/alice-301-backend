/** Демо-дом: план, устройства и сценарий голосовых команд.
 *  Геометрия комнат — в координатах SVG (viewBox 1200×820). */

export type Room = {
  id: string
  name: string
  x: number
  y: number
  w: number
  h: number
  /** центр светового пятна внутри комнаты, 0..1 от размеров комнаты */
  lightAt: [number, number]
}

export type Device = {
  id: string
  name: string
  roomId: string
  /** мощность свечения комнаты, когда устройство включено */
  intensity: number
  model: string
}

export const ROOMS: Room[] = [
  { id: 'living', name: 'Гостиная', x: 40, y: 40, w: 560, h: 340, lightAt: [0.42, 0.4] },
  { id: 'bedroom', name: 'Спальня', x: 616, y: 40, w: 544, h: 340, lightAt: [0.5, 0.45] },
  { id: 'kitchen', name: 'Кухня', x: 40, y: 396, w: 360, h: 384, lightAt: [0.5, 0.42] },
  { id: 'hall', name: 'Прихожая', x: 416, y: 396, w: 268, h: 384, lightAt: [0.5, 0.5] },
  { id: 'bath', name: 'Ванная', x: 700, y: 396, w: 184, h: 384, lightAt: [0.5, 0.42] },
  { id: 'study', name: 'Кабинет', x: 900, y: 396, w: 260, h: 384, lightAt: [0.5, 0.42] },
]

export const DEVICES: Device[] = [
  { id: 'lv-ceiling', name: 'Люстра', roomId: 'living', intensity: 1, model: 'TS0011' },
  { id: 'lv-floor', name: 'Торшер', roomId: 'living', intensity: 0.55, model: 'TS0505B' },
  { id: 'bd-sconce', name: 'Бра у кровати', roomId: 'bedroom', intensity: 0.6, model: 'TS0505B' },
  { id: 'kt-strip', name: 'Подсветка кухни', roomId: 'kitchen', intensity: 0.85, model: 'TS0503B' },
  { id: 'hl-light', name: 'Свет в прихожей', roomId: 'hall', intensity: 0.9, model: 'TS0011' },
  { id: 'bt-light', name: 'Свет в ванной', roomId: 'bath', intensity: 0.9, model: 'TS0011' },
  { id: 'st-lamp', name: 'Лампа на столе', roomId: 'study', intensity: 0.7, model: 'TS0505B' },
]

/** Реплики для демонстрации: что говорят Алисе и что происходит с домом. */
export type VoiceScript = {
  phrase: string
  /** какие устройства включить (true) или выключить (false) */
  set: Record<string, boolean>
  reply: string
}

export const VOICE_SCRIPTS: VoiceScript[] = [
  {
    phrase: 'Алиса, включи свет на кухне',
    set: { 'kt-strip': true },
    reply: 'Включила подсветку кухни',
  },
  {
    phrase: 'Алиса, включи лампу в кабинете',
    set: { 'st-lamp': true },
    reply: 'Готово, лампа на столе горит',
  },
  {
    phrase: 'Алиса, зажги свет в гостиной',
    set: { 'lv-ceiling': true, 'lv-floor': true },
    reply: 'Включила люстру и торшер',
  },
  {
    phrase: 'Алиса, выключи люстру',
    set: { 'lv-ceiling': false },
    reply: 'Выключила люстру, торшер оставила',
  },
  {
    phrase: 'Алиса, включи ночник в спальне',
    set: { 'bd-sconce': true },
    reply: 'Бра у кровати включено',
  },
  {
    phrase: 'Алиса, выключи всё',
    set: Object.fromEntries(DEVICES.map(d => [d.id, false])),
    reply: 'Выключила все семь светильников',
  },
]

/** Вечерняя сцена, к которой дом приходит после приветственной волны света. */
const EVENING = new Set(['hl-light', 'lv-floor', 'kt-strip'])

export const INITIAL_STATE: Record<string, boolean> = Object.fromEntries(
  DEVICES.map(d => [d.id, EVENING.has(d.id)]),
)

/** Телеметрия устройства — то же, что собирает десктопная панель агента:
 *  uptime, пинг, разбивка команд по источнику и активность по часам. */
export type CommandSplit = { alice: number; local: number; cloud: number }

export type DeviceStats = {
  uptimePct: number
  avgPingMs: number
  /** служебные проверки связи за сутки — считаются отдельно от команд:
   *  если смешать их с командами, счётчик разрастается в сотни раз */
  healthChecks: number
  /** пинг за последние 24 часа, мс */
  ping24h: number[]
  /** сколько команд пришло в каждый час суток */
  hourly: number[]
  on: CommandSplit
  off: CommandSplit
}

/** Детерминированный генератор: у каждого устройства свой,
 *  но стабильный между перезагрузками профиль нагрузки. */
function makeStats(seed: number, base: { uptime: number; ping: number; commands: number }): DeviceStats {
  let value = seed
  const next = () => {
    value = (value * 1103515245 + 12345) % 2147483648
    return value / 2147483648
  }
  const ping24h = Array.from({ length: 24 }, () => Math.round(base.ping * (0.72 + next() * 0.66)))
  // Люди щёлкают светом утром и вечером — активность повторяет этот ритм.
  const hourly = Array.from({ length: 24 }, (_, hour) => {
    const morning = Math.exp(-((hour - 8) ** 2) / 6)
    const evening = Math.exp(-((hour - 21) ** 2) / 8)
    return Math.round(base.commands * (morning + evening * 1.4) * (0.6 + next() * 0.8))
  })
  const total = hourly.reduce((sum, count) => sum + count, 0)
  const onTotal = Math.round(total * 0.52)
  const offTotal = total - onTotal
  const split = (amount: number): CommandSplit => {
    const alice = Math.round(amount * (0.5 + next() * 0.2))
    const local = Math.round((amount - alice) * (0.55 + next() * 0.25))
    return { alice, local, cloud: Math.max(0, amount - alice - local) }
  }
  return {
    uptimePct: base.uptime,
    avgPingMs: Math.round(ping24h.reduce((sum, p) => sum + p, 0) / ping24h.length),
    healthChecks: Math.round((1440 * base.uptime) / 100),
    ping24h,
    hourly,
    on: split(onTotal),
    off: split(offTotal),
  }
}

export const DEVICE_STATS: Record<string, DeviceStats> = {
  'lv-ceiling': makeStats(11, { uptime: 99.4, ping: 38, commands: 9 }),
  'lv-floor': makeStats(23, { uptime: 98.1, ping: 44, commands: 6 }),
  'bd-sconce': makeStats(37, { uptime: 99.8, ping: 31, commands: 7 }),
  'kt-strip': makeStats(41, { uptime: 97.2, ping: 52, commands: 12 }),
  'hl-light': makeStats(59, { uptime: 99.9, ping: 27, commands: 15 }),
  'bt-light': makeStats(67, { uptime: 99.1, ping: 35, commands: 8 }),
  'st-lamp': makeStats(83, { uptime: 96.5, ping: 61, commands: 5 }),
}
