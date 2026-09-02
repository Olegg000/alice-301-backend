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
