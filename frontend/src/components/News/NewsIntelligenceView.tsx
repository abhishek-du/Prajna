import React, { useEffect, useState } from 'react'
import {
  AlertCircle,
  Clock,
  ExternalLink,
  Filter,
  Newspaper,
  RefreshCw,
  Tag,
} from 'lucide-react'
import { api } from '../../services/api'
import type { NewsArticleItem } from '../../types/api'

interface NewsIntelligenceViewProps {
  onSelectInstrument?: (key: string) => void
}

export const NewsIntelligenceView: React.FC<NewsIntelligenceViewProps> = ({
  onSelectInstrument,
}) => {
  const [articles, setArticles] = useState<NewsArticleItem[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [filterClass, setFilterClass] = useState<string>('')

  const loadNews = async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await api.getNews({ limit: 50 })
      setArticles(res.articles)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load news articles')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadNews()
  }, [])

  const filteredArticles = filterClass
    ? articles.filter((a) => a.classification === filterClass)
    : articles

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* 1. Header & Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-slate-800 gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Newspaper className="w-5 h-5 text-amber-400" />
            News Intelligence & Provenance Feed
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Market-hours 30-min polling with publication, receipt and processing latency tracking
          </p>
        </div>

        <div className="flex items-center gap-3">
          <select
            value={filterClass}
            onChange={(e) => setFilterClass(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded px-2.5 py-1 text-slate-300 text-xs focus:outline-none"
          >
            <option value="">All Classifications</option>
            <option value="MARKET">Market-wide</option>
            <option value="SECTOR">Sector</option>
            <option value="STOCK">Stock-specific</option>
          </select>

          <button
            onClick={loadNews}
            className="p-2 bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 rounded-lg text-xs flex items-center gap-1.5"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Honest Policy Notice */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 text-xs text-slate-300 flex items-start gap-3">
        <AlertCircle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
        <div>
          <span className="font-bold text-slate-100">Sentiment & Impact Scores Policy:</span>{' '}
          In accordance with Stage 3 hardening rules, sentiment polarity and predicted market impact
          scores are not fabricated. Natural language processing models will be integrated in
          future phases once feature causality and point-in-time boundaries are formally verified.
        </div>
      </div>

      {loading && articles.length === 0 ? (
        <div className="py-20 text-center text-slate-400">
          <RefreshCw className="w-8 h-8 animate-spin mx-auto text-amber-400 mb-3" />
          <p className="text-xs">Loading news intelligence feed...</p>
        </div>
      ) : error && articles.length === 0 ? (
        <div className="p-8 max-w-lg mx-auto bg-rose-950/20 border border-rose-800/40 rounded-xl text-center">
          <p className="text-rose-400 text-xs mb-3">{error}</p>
          <button
            onClick={loadNews}
            className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-xs"
          >
            Retry
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredArticles.length === 0 ? (
            <div className="py-12 text-center text-slate-500 text-xs">
              No news articles match the filter
            </div>
          ) : (
            filteredArticles.map((article) => {
              const latencyHours =
                article.latency_seconds !== null
                  ? (article.latency_seconds / 3600).toFixed(1)
                  : null

              return (
                <div
                  key={article.news_id}
                  className="bg-slate-900/70 border border-slate-800/80 rounded-xl p-4 hover:border-slate-700 transition space-y-3"
                >
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-mono font-semibold uppercase ${
                          article.classification === 'STOCK'
                            ? 'bg-blue-950/60 text-blue-300 border border-blue-800/40'
                            : article.classification === 'SECTOR'
                            ? 'bg-purple-950/60 text-purple-300 border border-purple-800/40'
                            : 'bg-slate-800 text-slate-300'
                        }`}
                      >
                        {article.classification}
                      </span>
                      <span className="text-xs font-semibold text-slate-400">
                        {article.publisher || article.source}
                      </span>
                    </div>

                    {article.url && (
                      <a
                        href={article.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs text-slate-400 hover:text-cyan-400 flex items-center gap-1 self-start sm:self-auto"
                      >
                        <span>View Source</span>
                        <ExternalLink className="w-3.5 h-3.5" />
                      </a>
                    )}
                  </div>

                  <h3 className="text-sm font-bold text-slate-100 leading-snug">
                    {article.headline}
                  </h3>

                  {article.body && (
                    <p className="text-xs text-slate-300/80 line-clamp-3 leading-relaxed">
                      {article.body}
                    </p>
                  )}

                  {/* Affected Instruments Tags */}
                  {article.affected_instruments.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1.5 pt-1">
                      <Tag className="w-3 h-3 text-slate-500" />
                      <span className="text-[11px] text-slate-500">Affected:</span>
                      {article.affected_instruments.map((sym) => (
                        <button
                          key={sym}
                          onClick={() => onSelectInstrument && onSelectInstrument(`NSE_EQ|${sym}`)}
                          className="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 text-emerald-400 font-mono text-[10px] rounded transition"
                        >
                          {sym}
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Provenance Timestamps Strip */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 pt-2 border-t border-slate-800/60 text-[10px] font-mono text-slate-400">
                    <div>
                      <span className="text-slate-500">Published:</span>{' '}
                      <span className="text-slate-300">
                        {article.published_at
                          ? article.published_at.slice(0, 16).replace('T', ' ')
                          : 'N/A'}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-500">Received (Prajna):</span>{' '}
                      <span className="text-slate-300">
                        {article.received_at
                          ? article.received_at.slice(0, 16).replace('T', ' ')
                          : 'N/A'}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-500">Ingestion Latency:</span>{' '}
                      <span className="text-cyan-300">
                        {latencyHours !== null ? `${latencyHours}h` : 'Instant'}
                      </span>
                    </div>
                  </div>
                </div>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
