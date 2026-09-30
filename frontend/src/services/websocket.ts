/**
 * WebSocket Live Data Service for Prajna.
 * Manages streaming connection, subscriptions, heartbeat, reconnects and stale tick handling.
 */

export interface LiveTickMessage {
  type: 'tick'
  instrument_key: string
  timeframe: string
  bar_start_utc: string
  bar_start_ist: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  knowable_at: string | null
  stale: boolean
  age_seconds: number
}

type MessageListener = (data: LiveTickMessage) => void
type StatusListener = (status: 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED') => void

class WebSocketService {
  private ws: WebSocket | null = null
  private listeners: Set<MessageListener> = new Set()
  private statusListeners: Set<StatusListener> = new Set()
  private subscribedKeys: Set<string> = new Set(['NSE_INDEX|Nifty 50', 'NSE_INDEX|Nifty Bank'])
  private reconnectTimeout: number | null = null
  private reconnectAttempts = 0
  private maxReconnectDelay = 10000
  private status: 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED' = 'DISCONNECTED'

  public connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const wsUrl = `${protocol}//${host}/ws/live`

    try {
      this.ws = new WebSocket(wsUrl)
    } catch {
      this.handleReconnect()
      return
    }

    this.ws.onopen = () => {
      this.reconnectAttempts = 0
      this.setStatus('CONNECTED')
      if (this.subscribedKeys.size > 0) {
        this.sendSubscribe(Array.from(this.subscribedKeys))
      }
    }

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'tick') {
          this.notifyListeners(msg as LiveTickMessage)
        } else if (msg.type === 'ping') {
          this.ws?.send(JSON.stringify({ type: 'pong' }))
        }
      } catch {
        // ignore parse error
      }
    }

    this.ws.onclose = () => {
      this.setStatus('DISCONNECTED')
      this.handleReconnect()
    }

    this.ws.onerror = () => {
      this.ws?.close()
    }
  }

  private setStatus(newStatus: 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED'): void {
    this.status = newStatus
    this.statusListeners.forEach((listener) => listener(newStatus))
  }

  private handleReconnect(): void {
    if (this.reconnectTimeout) return
    this.setStatus('RECONNECTING')
    this.reconnectAttempts++
    const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), this.maxReconnectDelay)
    this.reconnectTimeout = window.setTimeout(() => {
      this.reconnectTimeout = null
      this.connect()
    }, delay)
  }

  private sendSubscribe(keys: string[]): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: 'subscribe', keys }))
    }
  }

  public subscribe(keys: string | string[]): void {
    const list = Array.isArray(keys) ? keys : [keys]
    list.forEach((k) => this.subscribedKeys.add(k))
    this.sendSubscribe(list)
  }

  public unsubscribe(keys: string | string[]): void {
    const list = Array.isArray(keys) ? keys : [keys]
    list.forEach((k) => this.subscribedKeys.delete(k))
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: 'unsubscribe', keys: list }))
    }
  }

  public onTick(listener: MessageListener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  public onStatus(listener: StatusListener): () => void {
    this.statusListeners.add(listener)
    listener(this.status)
    return () => this.statusListeners.delete(listener)
  }

  public onStatusChange(listener: StatusListener): () => void {
    return this.onStatus(listener)
  }

  private notifyListeners(data: LiveTickMessage): void {
    this.listeners.forEach((listener) => {
      try {
        listener(data)
      } catch {
        // ignore
      }
    })
  }

  public disconnect(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout)
      this.reconnectTimeout = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    this.setStatus('DISCONNECTED')
  }
}

export const wsService = new WebSocketService()
export const liveStreamService = wsService
