import React, { useEffect, useRef, useState } from 'react'
import {
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  createChart,
} from 'lightweight-charts'
import {
  AlertTriangle,
  Calendar,
  Clock,
  Maximize2,
  RefreshCw,
  Sliders,
  Wifi,
  WifiOff,
} from 'lucide-react'
import { api } from '../../services/api'
import { type LiveTickMessage, wsService } from '../../services/websocket'
import type { Candle } from '../../types/api'

interface CandleChartProps {
  instrumentKey: string
  tradingSymbol?: string
}

export const CandleChart: React.FC<CandleChartProps> = ({
  instrumentKey,
  tradingSymbol,
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)

  const [timeframe, setTimeframe] = useState<string>('1d')
  const [adjusted, setAdjusted] = useState<boolean>(false)
  const [tz, setTz] = useState<'IST' | 'UTC'>('IST')
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [candlesCount, setCandlesCount] = useState<number>(0)
  const [hoveredCandle, setHoveredCandle] = useState<Candle | null>(null)
  const [latestCandle, setLatestCandle] = useState<Candle | null>(null)
  const [isStale, setIsStale] = useState<boolean>(false)
  const [wsStatus, setWsStatus] = useState<'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED'>('DISCONNECTED')

  // Listen to WebSocket connection status
  useEffect(() => {
    return wsService.onStatus((status) => setWsStatus(status))
  }, [])

  // Subscribe to instrument live ticks
  useEffect(() => {
    if (!instrumentKey) return
    wsService.subscribe(instrumentKey)

    const unsubscribe = wsService.onTick((tick: LiveTickMessage) => {
      if (tick.instrument_key !== instrumentKey) return

      setIsStale(tick.stale)

      const timeSec = Math.floor(new Date(tick.bar_start_utc).getTime() / 1000) as UTCTimestamp

      const candleUpdate = {
        time: timeSec,
        open: tick.open,
        high: tick.high,
        low: tick.low,
        close: tick.close,
      }

      if (candleSeriesRef.current) {
        candleSeriesRef.current.update(candleUpdate)
      }

      if (volumeSeriesRef.current) {
        volumeSeriesRef.current.update({
          time: timeSec,
          value: tick.volume,
          color: tick.close >= tick.open ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
        })
      }

      setLatestCandle({
        timeframe: tick.timeframe,
        bar_start_utc: tick.bar_start_utc,
        bar_start_ist: tick.bar_start_ist,
        market_date: tick.bar_start_utc.slice(0, 10),
        open: tick.open,
        high: tick.high,
        low: tick.low,
        close: tick.close,
        volume: tick.volume,
        knowable_at: tick.knowable_at || tick.bar_start_utc,
      })
    })

    return () => {
      unsubscribe()
      wsService.unsubscribe(instrumentKey)
    }
  }, [instrumentKey, timeframe])

  // Initialize and resize chart
  useEffect(() => {
    if (!chartContainerRef.current) return

    const container = chartContainerRef.current
    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: '#090d16' },
        textColor: '#94a3b8',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(30, 41, 59, 0.5)' },
        horzLines: { color: 'rgba(30, 41, 59, 0.5)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: '#1e293b',
        scaleMargins: { top: 0.1, bottom: 0.25 },
      },
      timeScale: {
        borderColor: '#1e293b',
        timeVisible: timeframe !== '1d',
        secondsVisible: false,
      },
      width: container.clientWidth,
      height: 480,
    })

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    })

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    })

    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    })

    chartRef.current = chart
    candleSeriesRef.current = candleSeries
    volumeSeriesRef.current = volumeSeries

    // Crosshair hover listener for OHLC tooltips
    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.seriesData) {
        setHoveredCandle(null)
        return
      }
      const candleData = param.seriesData.get(candleSeries) as {
        open: number
        high: number
        low: number
        close: number
      } | undefined
      const volData = param.seriesData.get(volumeSeries) as { value: number } | undefined

      if (candleData) {
        setHoveredCandle({
          timeframe,
          bar_start_utc: String(param.time),
          bar_start_ist: '',
          market_date: String(param.time),
          open: candleData.open,
          high: candleData.high,
          low: candleData.low,
          close: candleData.close,
          volume: volData ? volData.value : 0,
          knowable_at: '',
        })
      }
    })

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth })
      }
    }

    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
      chartRef.current = null
      candleSeriesRef.current = null
      volumeSeriesRef.current = null
    }
  }, [timeframe])

  // Fetch historical candles and populate chart
  const loadCandles = async () => {
    if (!instrumentKey) return
    try {
      setLoading(true)
      setError(null)
      const res = await api.getCandles(instrumentKey, timeframe, {
        limit: 500,
        adjusted: adjusted && timeframe === '1d',
      })

      const rawCandles = res.candles
      setCandlesCount(rawCandles.length)

      if (rawCandles.length > 0) {
        setLatestCandle(rawCandles[rawCandles.length - 1])
      }

      // Convert to sorted lightweight-charts format
      const formattedCandles = rawCandles.map((c) => {
        const timeSec = Math.floor(new Date(c.bar_start_utc).getTime() / 1000) as UTCTimestamp
        return {
          time: timeSec,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        }
      })

      const formattedVolumes = rawCandles.map((c) => {
        const timeSec = Math.floor(new Date(c.bar_start_utc).getTime() / 1000) as UTCTimestamp
        return {
          time: timeSec,
          value: c.volume,
          color: c.close >= c.open ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
        }
      })

      if (candleSeriesRef.current) {
        candleSeriesRef.current.setData(formattedCandles)
      }
      if (volumeSeriesRef.current) {
        volumeSeriesRef.current.setData(formattedVolumes)
      }

      if (chartRef.current) {
        chartRef.current.timeScale().fitContent()
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load historical candles')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadCandles()
  }, [instrumentKey, timeframe, adjusted])

  const activeCandle = hoveredCandle || latestCandle
  const isUp = activeCandle ? activeCandle.close >= activeCandle.open : true

  return (
    <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-hidden shadow-lg">
      {/* Top Toolbar */}
      <div className="flex flex-wrap items-center justify-between px-4 py-2.5 border-b border-slate-800 bg-slate-950/70 gap-2">
        <div className="flex items-center space-x-3">
          <div className="font-bold text-sm text-slate-100 flex items-center gap-1.5">
            <span className="text-emerald-400">
              {tradingSymbol || instrumentKey.split('|')[1] || instrumentKey}
            </span>
            <span className="text-slate-500 font-mono text-xs">({instrumentKey})</span>
          </div>

          {/* Timeframe buttons */}
          <div className="flex items-center space-x-1 bg-slate-900 border border-slate-800 p-0.5 rounded-lg text-xs">
            {['1m', '15m', '1h', '1d'].map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-2.5 py-1 rounded text-xs font-semibold transition ${
                  timeframe === tf
                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {tf.toUpperCase()}
              </button>
            ))}
          </div>

          {/* Adjusted Toggle (for 1D only) */}
          {timeframe === '1d' && (
            <label className="flex items-center space-x-1.5 text-xs text-slate-400 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={adjusted}
                onChange={(e) => setAdjusted(e.target.checked)}
                className="rounded bg-slate-900 border-slate-700 text-emerald-500 focus:ring-0"
              />
              <span className={adjusted ? 'text-emerald-400 font-medium' : ''}>
                PIT Adjusted (Bonus/Split)
              </span>
            </label>
          )}
        </div>

        {/* Timezone, Live and Status indicators */}
        <div className="flex items-center space-x-3 text-xs">
          {/* Timezone toggle */}
          <button
            onClick={() => setTz((prev) => (prev === 'IST' ? 'UTC' : 'IST'))}
            className="flex items-center space-x-1 px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300 font-mono text-[11px]"
            title="Toggle Timezone Display"
          >
            <Clock className="w-3 h-3 text-slate-400" />
            <span>TZ: {tz}</span>
          </button>

          {/* WebSocket stream status */}
          <div className="flex items-center space-x-1 text-[11px] px-2 py-0.5 rounded bg-slate-800 border border-slate-700">
            {wsStatus === 'CONNECTED' ? (
              <>
                <Wifi className="w-3 h-3 text-emerald-400" />
                <span className="text-emerald-400">Stream Live</span>
              </>
            ) : (
              <>
                <WifiOff className="w-3 h-3 text-amber-400" />
                <span className="text-amber-400">Stream Off</span>
              </>
            )}
          </div>

          <button
            onClick={loadCandles}
            className="p-1.5 hover:bg-slate-800 rounded text-slate-400 hover:text-slate-200 transition"
            title="Refresh candles"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Stale Data Warning Banner */}
      {isStale && (
        <div className="bg-amber-950/60 border-b border-amber-800/60 px-4 py-1.5 text-xs text-amber-300 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            <span>Market Stale Warning: Last tick latency exceeded timing threshold</span>
          </div>
          <span className="text-[10px] text-amber-400 font-mono">Market closed or quiet</span>
        </div>
      )}

      {/* Live / Hovered OHLC Header Strip */}
      <div className="px-4 py-2 bg-slate-950/40 border-b border-slate-800/60 flex flex-wrap items-center justify-between text-xs gap-3 font-mono">
        {activeCandle ? (
          <div className="flex items-center space-x-4">
            <div>
              <span className="text-slate-500">O:</span>{' '}
              <span className="text-slate-200 font-bold">{activeCandle.open.toFixed(2)}</span>
            </div>
            <div>
              <span className="text-slate-500">H:</span>{' '}
              <span className="text-emerald-400 font-bold">{activeCandle.high.toFixed(2)}</span>
            </div>
            <div>
              <span className="text-slate-500">L:</span>{' '}
              <span className="text-rose-400 font-bold">{activeCandle.low.toFixed(2)}</span>
            </div>
            <div>
              <span className="text-slate-500">C:</span>{' '}
              <span className={`font-bold ${isUp ? 'text-emerald-400' : 'text-rose-400'}`}>
                {activeCandle.close.toFixed(2)}
              </span>
            </div>
            <div>
              <span className="text-slate-500">Vol:</span>{' '}
              <span className="text-slate-300">{activeCandle.volume.toLocaleString('en-IN')}</span>
            </div>
          </div>
        ) : (
          <div className="text-slate-500">Hover over a candle to inspect values</div>
        )}

        <div className="text-slate-400 text-[11px]">
          {candlesCount} bars loaded •{' '}
          <span className="text-slate-500">{adjusted ? 'PIT Adjusted' : 'Raw Canonical Basis'}</span>
        </div>
      </div>

      {/* Chart Canvas Area */}
      <div className="relative min-h-[480px]">
        {loading && (
          <div className="absolute inset-0 z-10 bg-slate-950/70 backdrop-blur-xs flex flex-col items-center justify-center text-slate-400">
            <RefreshCw className="w-8 h-8 animate-spin text-emerald-400 mb-2" />
            <span className="text-xs">Fetching canonical candles...</span>
          </div>
        )}

        {error && (
          <div className="absolute inset-0 z-10 bg-slate-950/90 flex flex-col items-center justify-center text-center p-6">
            <AlertTriangle className="w-8 h-8 text-rose-400 mb-2" />
            <p className="text-xs text-rose-300 mb-3">{error}</p>
            <button
              onClick={loadCandles}
              className="px-3 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-xs"
            >
              Retry
            </button>
          </div>
        )}

        <div ref={chartContainerRef} className="w-full h-[480px]" />
      </div>
    </div>
  )
}
