// AI 추정 / 실제 대사. 인식 결과마다 AI가 고른 큐(왼쪽)와 실제로 들린 시각·글자(오른쪽)를 나란히 쌓는다.
// 둘을 비교하면 추적이 맞는지, 어디서 어긋났는지 바로 보인다. 최신이 위.
// 오퍼레이터용이 아니라 팀의 성능 확인용이라 기본은 접어 두고, 눌렀을 때만 펼친다 (접혀 있어도 기록은 계속 쌓임).

import { useState } from 'react'
import type { Cue } from '../cues'
import { formatElapsed } from '../time'
import type { RecognitionEntry } from '../useEngine'

interface Props {
  entries: RecognitionEntry[]
  cueById: Map<number, Cue>
  startedAt: number
  threshold: number
}

export function RecognitionLog({ entries, cueById, startedAt, threshold }: Props) {
  const [open, setOpen] = useState(false)

  return (
    <section className="panel recog">
      <button className="recog-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="recog-caret">{open ? '▾' : '▸'}</span>
        성능 확인용: AI 추정 / 실제로 들린 말
        <span className="muted small">{entries.length}건</span>
      </button>
      {open && (
        <>
          <div className="recog-head">
            <h2>AI 추정</h2>
            <h2>실제로 들린 말</h2>
          </div>
          {entries.length === 0 ? (
            <p className="recog-empty">아직 인식된 말이 없습니다</p>
          ) : (
            <ol className="recog-list">
              {[...entries].reverse().map((e) => {
                const cue = cueById.get(e.cueId)
                const uncertain = e.confidence < threshold
                return (
                  <li key={`${e.at}-${e.cueId}`} className={uncertain ? 'recog-uncertain' : undefined}>
                    <span className="recog-ai">
                      <b>#{e.cueId}</b> {cue?.text ?? ''}
                      {uncertain && <span className="recog-tag">불확실 {e.confidence.toFixed(2)}</span>}
                    </span>
                    <span className="recog-heard">
                      <time>{formatElapsed(e.heardAt - startedAt)}</time>
                      <span className="recog-sep">|</span>
                      {e.transcript}
                    </span>
                  </li>
                )
              })}
            </ol>
          )}
        </>
      )}
    </section>
  )
}
