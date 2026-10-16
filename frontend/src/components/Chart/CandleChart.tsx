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
  createSeriesMarkers,
} from 'lightweight-charts'
import {
  AlertTriangle,
  Calendar,
  ChevronDown,
  ChevronUp,
  Clock,
  Maximize2,
  RefreshCw,
  ShieldAlert,
  Sliders,
  Tag,
  Wifi,
  WifiOff,
} from 'lucide-react'
import { api } from '../../services/api'
import { type LiveTickMessage, wsService } from '../../services/websocket'
import type { Candle, CorporateActionMarker, ExcludedBarMarker } from '../../types/api'

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
  const seriesMarkersRef = useRef<any>(null)

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
  const [corporateActions, setCorporateActions] = useState<CorporateActionMarker[]>([])
  const [excludedBars, setExcludedBars] = useState<ExcludedBarMarker[]>([])
  const [showMarkersDrawer, setShowMarkersDrawer] = useState<boolean>(true)

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
      if (seriesMarkersRef.current) {
        try {
          seriesMarkersRef.current.detach()
        } catch {
          // ignore
        }
        seriesMarkersRef.current = null
      }
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
      const caList = res.corporate_actions || []
      const ebList = res.excluded_bars || []
      setCorporateActions(caList)
      setExcludedBars(ebList)

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

      // Build markers for corporate actions and excluded bars
      const markers: Array<{
        time: UTCTimestamp
        position: 'aboveBar' | 'belowBar'
        color: string
        shape: 'arrowDown' | 'arrowUp' | 'circle' | 'square'
        text: string
        id?: string
      }> = []

      // Map market_date to formatted candle time
      const dateToCandleTime = new Map<string, UTCTimestamp>()
      rawCandles.forEach((c) => {
        const timeSec = Math.floor(new Date(c.bar_start_utc).getTime() / 1000) as UTCTimestamp
        dateToCandleTime.set(c.market_date, timeSec)
      })

      // Add Corporate Action markers
      caList.forEach((ca) => {
        let markerTime: UTCTimestamp | undefined = dateToCandleTime.get(ca.ex_date)
        if (!markerTime) {
          const match = rawCandles.find((c) => c.market_date >= ca.ex_date)
          if (match) {
            markerTime = Math.floor(new Date(match.bar_start_utc).getTime() / 1000) as UTCTimestamp
          }
        }
        if (markerTime) {
          let label = ca.action_type
          if (ca.ratio_from && ca.ratio_to) {
            label += ` ${ca.ratio_from}:${ca.ratio_to}`
          } else if (ca.amount) {
            label += ` ₹${ca.amount}`
          }
          markers.push({
            time: markerTime,
            position: 'aboveBar',
            color: '#38bdf8', // sky-400
            shape: 'arrowDown',
            text: `CA: ${label}`,
            id: `ca-${ca.id || ca.ex_date}`,
          })
        }
      })

      // Add Excluded Bar markers
      ebList.forEach((eb) => {
        let markerTime: UTCTimestamp | undefined
        if (timeframe === '1d') {
          markerTime = dateToCandleTime.get(eb.session_date)
        } else {
          const ebTimeSec = Math.floor(new Date(eb.bar_start_utc).getTime() / 1000)
          const match = formattedCandles.find((c) => Math.abs(Number(c.time) - ebTimeSec) <= 60)
          if (match) markerTime = match.time
        }
        if (!markerTime && rawCandles.length > 0) {
          const match = rawCandles.find((c) => c.market_date === eb.session_date)
          if (match) {
            markerTime = Math.floor(new Date(match.bar_start_utc).getTime() / 1000) as UTCTimestamp
          }
        }
        if (markerTime) {
          const shortReason = eb.reason.length > 20 ? `${eb.reason.substring(0, 18)}...` : eb.reason
          markers.push({
            time: markerTime,
            position: 'belowBar',
            color: '#f43f5e', // rose-500
            shape: 'arrowUp',
            text: `EXCL: ${shortReason}`,
            id: `eb-${eb.bar_start_utc}-${eb.reason}`,
          })
        }
      })

      // Sort markers strictly ascending by time
      markers.sort((a, b) => Number(a.time) - Number(b.time))

      if (candleSeriesRef.current) {
        if (!seriesMarkersRef.current) {
          seriesMarkersRef.current = createSeriesMarkers(candleSeriesRef.current, markers)
        } else {
          seriesMarkersRef.current.setMarkers(markers)
        }
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

      {/* Markers & Point-in-Time Corporate Action / Excluded Bar Drawer */}
      <div className="border-t border-slate-800 bg-slate-950/90 text-xs">
        <button
          onClick={() => setShowMarkersDrawer((prev) => !prev)}
          className="w-full px-4 py-2.5 flex items-center justify-between text-slate-300 hover:bg-slate-900/60 transition select-none"
        >
          <div className="flex items-center space-x-3">
            <span className="font-semibold text-slate-200 flex items-center gap-1.5">
              <Sliders className="w-3.5 h-3.5 text-emerald-400" />
              Chart Event Markers
            </span>
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono bg-sky-950/60 border border-sky-800 text-sky-300">
              <Tag className="w-3 h-3 text-sky-400" />
              {corporateActions.length} Corporate Action{corporateActions.length === 1 ? '' : 's'}
            </span>
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono bg-rose-950/60 border border-rose-800 text-rose-300">
              <ShieldAlert className="w-3 h-3 text-rose-400" />
              {excludedBars.length} Excluded Bar{excludedBars.length === 1 ? '' : 's'}
            </span>
          </div>
          <div className="flex items-center space-x-1.5 text-slate-400 text-xs">
            <span>{showMarkersDrawer ? 'Collapse' : 'Expand Details'}</span>
            {showMarkersDrawer ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </div>
        </button>

        {showMarkersDrawer && (
          <div className="px-4 pb-4 pt-1 space-y-3 border-t border-slate-800/60">
            {corporateActions.length === 0 && excludedBars.length === 0 ? (
              <p className="text-slate-500 py-2 text-center">
                No corporate actions or quarantined bars in the active chart range.
              </p>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Corporate Actions Summary Table */}
                <div>
                  <h4 className="text-xs font-semibold text-sky-400 uppercase tracking-wider mb-2 flex items-center gap-1">
                    <Tag className="w-3 h-3" />
                    Corporate Actions (Point-in-Time)
                  </h4>
                  {corporateActions.length === 0 ? (
                    <div className="text-slate-500 text-xs bg-slate-900/40 p-2.5 rounded border border-slate-800">
                      No corporate actions recorded for this instrument.
                    </div>
                  ) : (
                    <div className="overflow-x-auto rounded border border-slate-800 bg-slate-900/40">
                      <table className="w-full text-[11px] text-left">
                        <thead className="bg-slate-950/80 text-slate-400 border-b border-slate-800">
                          <tr>
                            <th className="px-2 py-1.5 font-medium">Ex-Date</th>
                            <th className="px-2 py-1.5 font-medium">Type</th>
                            <th className="px-2 py-1.5 font-medium">Ratio / Amt</th>
                            <th className="px-2 py-1.5 font-medium">Factor</th>
                            <th className="px-2 py-1.5 font-medium">Source</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800 font-mono">
                          {corporateActions.map((ca, idx) => (
                            <tr key={idx} className="hover:bg-slate-800/40">
                              <td className="px-2 py-1.5 text-slate-200">{ca.ex_date}</td>
                              <td className="px-2 py-1.5 text-sky-400 font-bold">{ca.action_type}</td>
                              <td className="px-2 py-1.5 text-slate-300">
                                {ca.ratio_from && ca.ratio_to
                                  ? `${ca.ratio_from}:${ca.ratio_to}`
                                  : ca.amount !== null && ca.amount !== undefined
                                    ? `₹${ca.amount}`
                                    : '—'}
                              </td>
                              <td className="px-2 py-1.5 text-slate-400">
                                {ca.factor !== null && ca.factor !== undefined ? ca.factor.toFixed(4) : '—'}
                              </td>
                              <td className="px-2 py-1.5 text-slate-500">{ca.source || '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>

                {/* Excluded Bars Summary Table */}
                <div>
                  <h4 className="text-xs font-semibold text-rose-400 uppercase tracking-wider mb-2 flex items-center gap-1">
                    <ShieldAlert className="w-3 h-3" />
                    Quarantined / Excluded Bars (Canon Exclusions)
                  </h4>
                  {excludedBars.length === 0 ? (
                    <div className="text-slate-500 text-xs bg-slate-900/40 p-2.5 rounded border border-slate-800">
                      No bars quarantined or excluded in this timeframe window.
                    </div>
                  ) : (
                    <div className="overflow-x-auto rounded border border-slate-800 bg-slate-900/40 max-h-48">
                      <table className="w-full text-[11px] text-left">
                        <thead className="bg-slate-950/80 text-slate-400 border-b border-slate-800 sticky top-0">
                          <tr>
                            <th className="px-2 py-1.5 font-medium">Date</th>
                            <th className="px-2 py-1.5 font-medium">Bar Start (IST)</th>
                            <th className="px-2 py-1.5 font-medium">Timeframe</th>
                            <th className="px-2 py-1.5 font-medium">Exclusion Reason</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800 font-mono">
                          {excludedBars.map((eb, idx) => (
                            <tr key={idx} className="hover:bg-slate-800/40">
                              <td className="px-2 py-1.5 text-slate-200">{eb.session_date}</td>
                              <td className="px-2 py-1.5 text-slate-400">{eb.bar_start_ist || eb.bar_start_utc}</td>
                              <td className="px-2 py-1.5 text-slate-300 uppercase">{eb.timeframe}</td>
                              <td className="px-2 py-1.5 text-rose-400 font-sans">{eb.reason}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
