import { useCallback, useEffect, useMemo, useState } from 'react'
import { FloorPlan } from './components/FloorPlan'
import { VoicePanel, type Turn } from './components/VoicePanel'
import { DEVICES, INITIAL_STATE, ROOMS, type VoiceScript } from './data/home'
import { DemoBackend, LiveBackend, type DeviceState, type HomeBackend } from './lib/api'

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

export default function App() {
  const [backend, setBackend] = useState<HomeBackend>(() => new DemoBackend())
  const [devices, setDevices] = useState(DEVICES)
  const [state, setState] = useState<DeviceState>(() =>
    Object.fromEntries(DEVICES.map(d => [d.id, false])),
  )
  const [latency, setLatency] = useState(0)
  const [log, setLog] = useState<Turn[]>([])
  const [busy, setBusy] = useState(false)
  const [showConnect, setShowConnect] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  /* Дом просыпается: свет пробегает по комнатам и оседает вечерней сценой. */
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      for (const device of DEVICES) {
        await sleep(150)
        if (cancelled) return
        setState(previous => ({ ...previous, [device.id]: true }))
      }
      await sleep(950)
      if (cancelled) return
      setState({ ...INITIAL_STATE })
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const litCount = useMemo(() => devices.filter(d => state[d.id]).length, [devices, state])

  const applyToDevice = useCallback(
    async (id: string, on: boolean) => {
      setState(previous => ({ ...previous, [id]: on }))
      try {
        await backend.setDevice(id, on)
        setLatency(backend.lastLatencyMs)
        setError(null)
      } catch (cause) {
        setState(previous => ({ ...previous, [id]: !on }))
        setError(cause instanceof Error ? cause.message : 'Не удалось отправить команду')
      }
    },
    [backend],
  )

  const toggleRoom = useCallback(
    (roomId: string) => {
      const inRoom = devices.filter(d => d.roomId === roomId)
      if (inRoom.length === 0) return
      const turnOn = !inRoom.some(d => state[d.id])
      inRoom.forEach(device => void applyToDevice(device.id, turnOn))
    },
    [applyToDevice, devices, state],
  )

  const say = useCallback(
    async (script: VoiceScript) => {
      setBusy(true)
      setLog(previous => [...previous.slice(-3), { phrase: script.phrase, reply: null }])
      await sleep(420)
      for (const [id, on] of Object.entries(script.set)) {
        if (state[id] !== on) await applyToDevice(id, on)
      }
      setLog(previous =>
        previous.map((turn, index) =>
          index === previous.length - 1 ? { ...turn, reply: script.reply } : turn,
        ),
      )
      setBusy(false)
    },
    [applyToDevice, state],
  )

  const connect = useCallback(async () => {
    setError(null)
    const live = new LiveBackend(url.trim(), token.trim())
    try {
      const remoteDevices = await live.listDevices()
      if (remoteDevices.length === 0) {
        setError('Сервер ответил, но не отдал ни одного устройства.')
        return
      }
      const remoteState = await live.readState()
      setDevices(remoteDevices)
      setState(remoteState)
      setBackend(live)
      setLatency(live.lastLatencyMs)
      setShowConnect(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось подключиться')
    }
  }, [token, url])

  const backToDemo = useCallback(() => {
    setBackend(new DemoBackend())
    setDevices(DEVICES)
    setState({ ...INITIAL_STATE })
    setError(null)
    setShowConnect(false)
  }, [])

  const live = backend.kind === 'live'

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <span className="bulb" />
          <span>
            Alice-SmartLight
            <small>панель управления домом</small>
          </span>
        </div>
        <div className="spacer" />
        <button
          className={`pill${live ? ' live' : ''}`}
          onClick={() => setShowConnect(value => !value)}
        >
          <span className="dot" />
          {live ? 'СВОЙ СЕРВЕР' : 'ДЕМО-ДОМ'}
        </button>
      </header>

      <div className="layout">
        <section className="card plan-card">
          <header>
            <h2>План квартиры</h2>
            <span className="label" style={{ marginLeft: 'auto' }}>
              нажмите комнату, чтобы переключить свет
            </span>
          </header>
          <div className="plan-wrap">
            <FloorPlan state={state} onToggleRoom={toggleRoom} />
          </div>
          <div className="plan-legend">
            <span className="legend-item">
              <span className="legend-dot on" /> свет включён
            </span>
            <span className="legend-item">
              <span className="legend-dot" /> выключен
            </span>
            <span className="legend-item mono" style={{ marginLeft: 'auto' }}>
              {ROOMS.length} комнат · {devices.length} светильников
            </span>
          </div>
          <div className="status">
            <div>
              <b className="lit">
                {litCount}/{devices.length}
              </b>
              <span>горит сейчас</span>
            </div>
            <div>
              <b className="cool">{latency || '—'}</b>
              <span>задержка, мс</span>
            </div>
            <div>
              <b>{live ? 'сервер' : 'локально'}</b>
              <span>источник данных</span>
            </div>
            <div>
              <b>WS</b>
              <span>канал до агента</span>
            </div>
          </div>
        </section>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {showConnect && (
            <section className="card">
              <header>
                <h2>Подключить свой дом</h2>
              </header>
              <div className="connect">
                <p>
                  Панель говорит с сервером теми же запросами, что и Яндекс Алиса:{' '}
                  <span className="mono">/v1.0/user/devices</span>,{' '}
                  <span className="mono">query</span>, <span className="mono">action</span>.
                </p>
                <label>
                  Адрес сервера
                  <input
                    value={url}
                    onChange={event => setUrl(event.target.value)}
                    placeholder="https://alice.example.com"
                    spellCheck={false}
                  />
                </label>
                <label>
                  Токен доступа
                  <input
                    value={token}
                    onChange={event => setToken(event.target.value)}
                    placeholder="Bearer-токен из привязки аккаунта"
                    spellCheck={false}
                    type="password"
                  />
                </label>
                {error && <p className="error">{error}</p>}
                <div className="row">
                  <button className="btn" onClick={connect} disabled={!url.trim() || !token.trim()}>
                    Подключиться
                  </button>
                  <button className="btn ghost" onClick={backToDemo}>
                    Вернуться к демо
                  </button>
                </div>
              </div>
            </section>
          )}

          <section className="card">
            <header>
              <h2>Светильники</h2>
              <span className="label" style={{ marginLeft: 'auto' }}>
                {litCount} из {devices.length}
              </span>
            </header>
            <div className="devices">
              {devices.map(device => {
                const on = Boolean(state[device.id])
                const room = ROOMS.find(r => r.id === device.roomId)
                return (
                  <button
                    key={device.id}
                    className={`device${on ? ' is-on' : ''}`}
                    onClick={() => void applyToDevice(device.id, !on)}
                    aria-pressed={on}
                  >
                    <span className="knob" />
                    <span className="name">
                      <b>{device.name}</b>
                      <span>
                        {room?.name ?? '—'} · {device.model}
                      </span>
                    </span>
                  </button>
                )
              })}
            </div>
          </section>

          <section className="card">
            <header>
              <h2>Голосовые команды</h2>
              <span className="label" style={{ marginLeft: 'auto' }}>
                Яндекс Алиса
              </span>
            </header>
            <VoicePanel log={log} busy={busy} onSay={say} />
          </section>
        </div>
      </div>

      <footer className="foot">
        <span>
          Демо-панель к бекенду <b style={{ color: 'var(--ink-soft)' }}>Alice-SmartLight</b>: облако
          между Яндекс Алисой и домом.
        </span>
        <a href="https://github.com/Olegg000/alice-301-backend">Исходный код</a>
        <a href="https://olegg000.github.io/lendvis/">Лендвис</a>
      </footer>
    </div>
  )
}
