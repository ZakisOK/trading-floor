'use client'
import { useState, useEffect } from 'react'

interface PolySignal {
  question: string
  yes_probability: number
  no_probability: number
  volume_24h: number
  relevance: string
  implication: string
  end_date: string
}

const relevanceColors: Record<string, string> = {
  XRP: 'var(--accent-cyan)',
  BTC: 'var(--status-caution)',
  MACRO: 'var(--accent-primary)',
  CRYPTO: 'var(--status-normal)',
}

export default function PolymarketPage() {
  const [signals, setSignals] = useState<PolySignal[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/market/polymarket/signals?symbol=XRP/USDT')
      .then(r => r.json())
      .then(d => { setSignals(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  return (
    <div style={{ padding: 'var(--space-6)' }}>
      <div style={{ marginBottom: 'var(--space-6)' }}>
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.04em', marginBottom: 8 }}>
          Polymarket Signals
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
          Prediction market probabilities — live crowd intelligence feeding agent conviction scores
        </p>
      </div>

      {loading ? (
        <div className="glass-panel" style={{ padding: 'var(--space-8)', textAlign: 'center', color: 'var(--text-tertiary)' }}>
          Fetching prediction markets...
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {signals.map((sig, i) => (
            <div key={i} className="card" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 'var(--space-4)' }}>
                <div style={{ flex: 1 }}>
                  <span style={{
                    display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 10,
                    fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase',
                    background: `${relevanceColors[sig.relevance]}22`,
                    color: relevanceColors[sig.relevance],
                    marginBottom: 6,
                  }}>
                    {sig.relevance}
                  </span>
                  <p style={{ fontSize: 14, color: 'var(--text-primary)', lineHeight: 1.4 }}>{sig.question}</p>
                </div>
                <div style={{ textAlign: 'right', flexShrink: 0 }}>
                  <div style={{
                    fontSize: 28, fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums',
                    fontWeight: 600, color: sig.yes_probability > 0.6 ? 'var(--accent-profit)' : sig.yes_probability < 0.4 ? 'var(--accent-loss)' : 'var(--text-primary)',
                    letterSpacing: '-0.02em',
                  }}>
                    {(sig.yes_probability * 100).toFixed(0)}%
                  </div>
                  <div className="label-micro">YES probability</div>
                </div>
              </div>

              {/* Probability bar */}
              <div style={{ height: 4, borderRadius: 2, background: 'var(--bg-surface-3)', overflow: 'hidden' }}>
                <div style={{
                  height: '100%', borderRadius: 2,
                  width: `${sig.yes_probability * 100}%`,
                  background: sig.yes_probability > 0.6 ? 'var(--accent-profit)' : sig.yes_probability < 0.4 ? 'var(--accent-loss)' : 'var(--accent-primary)',
                  transition: 'width 0.3s ease',
                }} />
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>{sig.implication}</span>
                <span className="mono" style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
                  Vol: ${(sig.volume_24h / 1000).toFixed(1)}k
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
