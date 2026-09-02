import { DEVICE_STATS, type CommandSplit, type Device } from '../data/home'

type Props = {
  device: Device
  onClose: () => void
}

const SOURCES: { key: keyof CommandSplit; label: string; className: string }[] = [
  { key: 'alice', label: 'Алиса', className: 'src-alice' },
  { key: 'local', label: 'Локально', className: 'src-local' },
  { key: 'cloud', label: 'Облако', className: 'src-cloud' },
]

function Split({ title, split }: { title: string; split: CommandSplit }) {
  const total = split.alice + split.local + split.cloud || 1
  return (
    <div className="split">
      <div className="split-head">
        <span>{title}</span>
        <b className="mono">{total}</b>
      </div>
      <div className="split-bar">
        {SOURCES.map(source => (
          <span
            key={source.key}
            className={source.className}
            style={{ width: `${(split[source.key] / total) * 100}%` }}
          />
        ))}
      </div>
      <ul className="split-legend">
        {SOURCES.map(source => (
          <li key={source.key}>
            <i className={source.className} />
            {source.label}
            <b className="mono">{split[source.key]}</b>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function DeviceStats({ device, onClose }: Props) {
  const stats = DEVICE_STATS[device.id]
  if (!stats) return null

  const maxPing = Math.max(...stats.ping24h)
  const minPing = Math.min(...stats.ping24h)
  const span = Math.max(1, maxPing - minPing)
  const points = stats.ping24h
    .map((ping, index) => {
      const x = (index / (stats.ping24h.length - 1)) * 300
      const y = 60 - ((ping - minPing) / span) * 48
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  const maxHourly = Math.max(...stats.hourly, 1)
  const totalCommands = stats.hourly.reduce((sum, count) => sum + count, 0)

  return (
    <section className="card">
      <header>
        <h2>{device.name}</h2>
        <span className="label" style={{ marginLeft: 'auto' }}>телеметрия</span>
        <button className="close" onClick={onClose} aria-label="Закрыть статистику">
          ✕
        </button>
      </header>

      <div className="stats">
        <div className="stat-row">
          <div>
            <b className="mono">{stats.uptimePct}%</b>
            <span>на связи</span>
          </div>
          <div>
            <b className="mono">{stats.avgPingMs} мс</b>
            <span>средний пинг</span>
          </div>
          <div>
            <b className="mono">{totalCommands}</b>
            <span>команд за сутки</span>
          </div>
        </div>

        <div className="chart">
          <div className="chart-head">
            <span className="label">пинг за 24 часа</span>
            <span className="mono chart-range">
              {minPing}–{maxPing} мс
            </span>
          </div>
          <svg viewBox="0 0 300 64" preserveAspectRatio="none" className="spark" aria-hidden="true">
            <polyline points={points} />
          </svg>
        </div>

        <div className="chart">
          <div className="chart-head">
            <span className="label">активность по часам</span>
            <span className="mono chart-range">пик {stats.hourly.indexOf(maxHourly)}:00</span>
          </div>
          <div className="bars">
            {stats.hourly.map((count, hour) => (
              <span
                key={hour}
                style={{ height: `${Math.max(4, (count / maxHourly) * 100)}%` }}
                title={`${hour}:00 — ${count} команд`}
              />
            ))}
          </div>
        </div>

        <Split title="Включения" split={stats.on} />
        <Split title="Выключения" split={stats.off} />
      </div>
    </section>
  )
}
