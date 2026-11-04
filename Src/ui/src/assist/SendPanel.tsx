// 자막 송출. AI가 추천한 큐를 오퍼레이터가 확인하고 직접 내보낸다 (자동 송출 없음, 마지막 판단은 사람).
// 복귀 직후에는 복귀 큐를 추천한다. 위치가 틀리면 대본 목록에서 줄을 눌러 고친 뒤 송출한다.
// 단축키 Space (입력칸에 쓰는 중이 아닐 때).

import { useEffect, useRef } from 'react'
import type { Cue } from '../cues'

interface Props {
  /** 송출할 추천 큐 */
  cue: Cue | undefined
  /** 함께 띄울 짧은 대사 */
  followers: Cue[]
  /** 마지막으로 송출한 대본 큐 */
  sentId: number | null
  /** 대본 이탈 중이면 추천이 오래된 위치일 수 있음 */
  deviating: boolean
  onSend: (cue: Cue) => void
}

// 글자를 쓰는 칸에서는 Space 가 띄어쓰기
const typing = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)

export function SendPanel({ cue, followers, sentId, deviating, onSend }: Props) {
  // 단축키 처리는 최신 값으로 (매번 리스너를 다시 달지 않게)
  const latest = useRef({ cue, onSend })
  useEffect(() => {
    latest.current = { cue, onSend }
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== 'Space' || e.repeat || typing(e.target)) return
      const { cue: c, onSend: send } = latest.current
      if (!c) return
      // 다른 버튼(회차 종료 등)에 포커스가 있어도 Space 는 송출만 하고, 그 버튼은 누르지 않게 한다
      e.preventDefault()
      if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
      send(c)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const sent = cue !== undefined && cue.id === sentId

  return (
    <section className={`panel send ${deviating ? 'send-deviating' : ''}`} aria-label="자막 송출">
      <div className="send-head">
        <h2>{deviating ? 'AI 추천 큐 · 이탈 중 (확인 필요)' : 'AI 추천 큐'}</h2>
        {sent && <span className="send-done">송출됨</span>}
      </div>
      <div className="send-row">
        <div className="send-cue">
          {cue ? (
            <>
              <span className="send-id">#{cue.id}</span>
              <span className="send-text">
                {cue.text}
                {followers.map((f) => (
                  <span key={f.id} className="send-follower">
                    #{f.id} {f.text}
                  </span>
                ))}
              </span>
            </>
          ) : (
            <span className="send-text muted">추천할 위치를 기다리는 중</span>
          )}
        </div>
        <button className="send-button" disabled={!cue} onClick={() => cue && onSend(cue)}>
          {sent ? '다시 송출' : '송출'}
          <span className="send-key">Space</span>
        </button>
      </div>
    </section>
  )
}
