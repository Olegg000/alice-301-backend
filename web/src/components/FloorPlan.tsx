import { ROOMS, DEVICES, type Room } from '../data/home'
import { Furniture } from './Furniture'
import type { DeviceState } from '../lib/api'

type Props = {
  state: DeviceState
  onToggleRoom: (roomId: string) => void
}

/** Яркость комнаты — самое сильное из включённых в ней устройств. */
function roomLevel(room: Room, state: DeviceState): number {
  return DEVICES.filter(d => d.roomId === room.id && state[d.id]).reduce(
    (max, d) => Math.max(max, d.intensity),
    0,
  )
}

const lampPoint = (room: Room) => ({
  x: room.x + room.w * room.lightAt[0],
  y: room.y + room.h * room.lightAt[1],
})

export function FloorPlan({ state, onToggleRoom }: Props) {
  return (
    <svg className="plan" viewBox="0 0 1200 820" role="img" aria-label="План квартиры со светом по комнатам">
      <defs>
        <linearGradient id="room-off" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#1a2531" />
          <stop offset="100%" stopColor="#101825" />
        </linearGradient>
        <filter id="soft" x="-70%" y="-70%" width="240%" height="240%">
          <feGaussianBlur stdDeviation="9" />
        </filter>
        {/* Свет рисуется прямоугольником самой комнаты: за стены он выйти не может,
            поэтому у каждой комнаты свой градиент с центром в лампе. */}
        {ROOMS.map(room => {
          const lamp = lampPoint(room)
          return (
            <radialGradient
              key={room.id}
              id={`glow-${room.id}`}
              gradientUnits="userSpaceOnUse"
              cx={lamp.x}
              cy={lamp.y}
              r={Math.max(room.w, room.h) * 0.62}
            >
              <stop offset="0%" stopColor="#ffd08a" stopOpacity="0.92" />
              <stop offset="30%" stopColor="#ffb04a" stopOpacity="0.46" />
              <stop offset="62%" stopColor="#d9761d" stopOpacity="0.17" />
              <stop offset="100%" stopColor="#8a4a10" stopOpacity="0.04" />
            </radialGradient>
          )
        })}
      </defs>

      {ROOMS.map(room => {
        const level = roomLevel(room, state)
        const on = level > 0
        const devicesHere = DEVICES.filter(d => d.roomId === room.id)
        const litHere = devicesHere.filter(d => state[d.id]).length
        const lamp = lampPoint(room)

        return (
          <g
            key={room.id}
            className={`room${on ? ' is-on' : ''}`}
            onClick={() => onToggleRoom(room.id)}
            role="button"
            tabIndex={0}
            aria-pressed={on}
            aria-label={`${room.name}: ${litHere} из ${devicesHere.length} светильников включено`}
            onKeyDown={event => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onToggleRoom(room.id)
              }
            }}
          >
            <rect
              className="room-shape"
              x={room.x}
              y={room.y}
              width={room.w}
              height={room.h}
              rx="14"
              fill="url(#room-off)"
            />

            <g className="room-glow" style={{ opacity: on ? level : 0 }}>
              <rect
                x={room.x}
                y={room.y}
                width={room.w}
                height={room.h}
                rx="14"
                fill={`url(#glow-${room.id})`}
              />
              <ellipse cx={lamp.x} cy={lamp.y} rx="16" ry="16" fill="#ffe3b6" filter="url(#soft)" />
              <circle cx={lamp.x} cy={lamp.y} r="4.5" fill="#fff3dd" />
            </g>

            {!on && <circle cx={lamp.x} cy={lamp.y} r="4.5" fill="#2f3b48" />}

            <Furniture roomId={room.id} />

            <text className="room-name" x={room.x + 20} y={room.y + 32}>
              {room.name}
            </text>
            <text className="room-meta" x={room.x + 20} y={room.y + 52}>
              {litHere}/{devicesHere.length} · {on ? `${Math.round(level * 100)}%` : 'выкл'}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
