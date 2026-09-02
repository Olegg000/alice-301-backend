import { VOICE_SCRIPTS, type VoiceScript } from '../data/home'

export type Turn = { phrase: string; reply: string | null }

type Props = {
  log: Turn[]
  busy: boolean
  onSay: (script: VoiceScript) => void
}

export function VoicePanel({ log, busy, onSay }: Props) {
  return (
    <div className="voice">
      <div className="voice-log">
        {log.length === 0 && (
          <p style={{ margin: 0, fontSize: 13.5, color: 'var(--ink-faint)' }}>
            Скажите Алисе фразу — дом ответит и поменяет свет на плане.
          </p>
        )}
        {log.map((turn, index) => (
          <div className="turn" key={`${turn.phrase}-${index}`}>
            <div className="said">{turn.phrase}</div>
            <div className={`replied${turn.reply === null ? ' thinking' : ''}`}>
              {turn.reply ?? 'Алиса думает…'}
            </div>
          </div>
        ))}
      </div>

      <div className="voice-actions">
        {VOICE_SCRIPTS.map(script => (
          <button
            key={script.phrase}
            className="phrase-btn"
            disabled={busy}
            onClick={() => onSay(script)}
          >
            {script.phrase.replace('Алиса, ', '')}
          </button>
        ))}
      </div>
    </div>
  )
}
