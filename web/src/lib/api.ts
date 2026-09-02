/** Два источника данных для панели: демо-дом в памяти и живой сервер Alice-SmartLight.
 *  Интерфейс общий, поэтому интерфейс панели не знает, с чем работает. */

import { DEVICES, INITIAL_STATE, type Device } from '../data/home'

export type DeviceState = Record<string, boolean>

export interface HomeBackend {
  readonly kind: 'demo' | 'live'
  listDevices(): Promise<Device[]>
  readState(): Promise<DeviceState>
  setDevice(id: string, on: boolean): Promise<void>
  /** Задержка последнего обмена, мс — панель показывает её в статусной строке. */
  readonly lastLatencyMs: number
}

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

/** Демо: состояние живёт в памяти вкладки, задержка имитирует канал до дома. */
export class DemoBackend implements HomeBackend {
  readonly kind = 'demo' as const
  lastLatencyMs = 0
  private state: DeviceState = { ...INITIAL_STATE }

  async listDevices(): Promise<Device[]> {
    await this.roundtrip()
    return DEVICES
  }

  async readState(): Promise<DeviceState> {
    await this.roundtrip()
    return { ...this.state }
  }

  async setDevice(id: string, on: boolean): Promise<void> {
    await this.roundtrip()
    this.state[id] = on
  }

  private async roundtrip() {
    const latency = 38 + Math.round(Math.random() * 34)
    await sleep(latency)
    this.lastLatencyMs = latency
  }
}

/** Живой сервер: те же эндпоинты, которые вызывает Яндекс Алиса. */
export class LiveBackend implements HomeBackend {
  readonly kind = 'live' as const
  lastLatencyMs = 0

  constructor(
    private readonly baseUrl: string,
    private readonly token: string,
  ) {}

  private async call<T>(path: string, init?: RequestInit): Promise<T> {
    const started = performance.now()
    const response = await fetch(this.baseUrl.replace(/\/$/, '') + path, {
      ...init,
      headers: {
        Authorization: `Bearer ${this.token}`,
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    })
    this.lastLatencyMs = Math.round(performance.now() - started)
    if (!response.ok) {
      throw new Error(`${path} вернул ${response.status}. Проверьте адрес сервера и токен.`)
    }
    return response.json() as Promise<T>
  }

  async listDevices(): Promise<Device[]> {
    type Payload = { payload: { devices: { id: string; name: string; device_info?: { model?: string } }[] } }
    const data = await this.call<Payload>('/v1.0/user/devices')
    // У сервера нет понятия комнаты, поэтому раскладываем устройства по плану
    // в том же порядке, в каком их отдаёт дом.
    return data.payload.devices.map((device, index) => ({
      id: device.id,
      name: device.name,
      roomId: DEVICES[index % DEVICES.length].roomId,
      intensity: DEVICES[index % DEVICES.length].intensity,
      model: device.device_info?.model ?? 'Smart Device',
    }))
  }

  async readState(): Promise<DeviceState> {
    type Payload = {
      payload: {
        devices: { id: string; capabilities?: { state?: { instance: string; value: boolean } }[] }[]
      }
    }
    const devices = await this.listDevices()
    const data = await this.call<Payload>('/v1.0/user/devices/query', {
      method: 'POST',
      body: JSON.stringify({ devices: devices.map(d => ({ id: d.id })) }),
    })
    const state: DeviceState = {}
    for (const device of data.payload.devices) {
      const capability = device.capabilities?.find(c => c.state?.instance === 'on')
      state[device.id] = Boolean(capability?.state?.value)
    }
    return state
  }

  async setDevice(id: string, on: boolean): Promise<void> {
    await this.call('/v1.0/user/devices/action', {
      method: 'POST',
      body: JSON.stringify({
        payload: {
          devices: [
            {
              id,
              actions: [
                {
                  type: 'devices.capabilities.on_off',
                  state: { instance: 'on', value: on },
                },
              ],
            },
          ],
        },
      }),
    })
  }
}
