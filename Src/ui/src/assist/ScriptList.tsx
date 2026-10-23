// ③ 대본 목록 + ① 현재 위치와 신뢰도.
// 전체 큐를 그리고 AI가 추정한 줄을 가운데로 따라간다. 손으로 스크롤하면 잠시 따라가기를 멈춘다.
// 위치 맞추기: 줄을 누르거나 이전/다음 버튼으로 AI 추정 위치를 고친다 (엔진에 position.set, 송출 아님).

import { useEffect, useMemo, useRef, useState } from 'react'
import { CUE_TYPE_LABEL, type Cue } from '../cues'
import { MANUAL_SCROLL_PAUSE_MS } from '../settings'

interface Props {
  cues: Cue[]
  currentId: number | null
  confidence: number | null
  /** 신뢰도가 이 값 미만이면 '불확실' 표시 */
  threshold: number
  /** 크게 보여 주는 중인 복귀 큐 */
  returnId: number | null
  /** 음향 입력이 없으면 현재 줄 표시를 흐리게 */
  paused: boolean
  /** 위치 맞추기: 이 큐로 AI 추정 위치를 옮긴다 */
  onJump: (cueId: number) => void
}

export function ScriptList({ cues, currentId, confidence, threshold, returnId, paused, onJump }: Props) {
  const listRef = useRef<HTMLOListElement>(null)
  const rowRefs = useRef(new Map<number, HTMLLIElement>())
  const [manualUntil, setManualUntil] = useState(0)
  const following = manualUntil === 0

  // 손으로 스크롤한 뒤 일정 시간이 지나면 다시 따라간다
  useEffect(() => {
    if (manualUntil === 0) return
    const timer = setTimeout(() => setManualUntil(0), Math.max(0, manualUntil - Date.now()))
    return () => clearTimeout(timer)
  }, [manualUntil])

  // scrollIntoView는 페이지까지 스크롤해 알림 카드를 밀어내므로, 목록 안에서만 스크롤한다
  useEffect(() => {
    const list = listRef.current
    const row = currentId === null ? undefined : rowRefs.current.get(currentId)
    if (!following || !list || !row) return
    const top = row.offsetTop - (list.clientHeight - row.offsetHeight) / 2
    list.scrollTo({ top, behavior: 'smooth' })
  }, [currentId, following])

  const pauseFollowing = () => setManualUntil(Date.now() + MANUAL_SCROLL_PAUSE_MS)
  const resumeFollowing = () => setManualUntil(0)

  // 이전 / 다음은 엔진이 따라가는 줄(대사 · 가사)끼리만
  const spoken = useMemo(() => cues.filter((c) => c.type === 'dialogue' || c.type === 'lyric'), [cues])
  const at = spoken.findIndex((c) => c.id === currentId)
  const prev = at > 0 ? spoken[at - 1] : undefined
  const next = at >= 0 ? spoken[at + 1] : spoken[0]
  const jump = (cueId: number) => {
    resumeFollowing()
    onJump(cueId)
  }

  const uncertain = confidence !== null && confidence < threshold

  return (
    <section className="panel script">
      <header className="panel-head">
        <h2>대본 목록</h2>
        <div className="script-nav">
          {!following && (
            <button className="ghost small" onClick={resumeFollowing}>
              현재 위치로
            </button>
          )}
          <button
            className="ghost small"
            disabled={!prev}
            onClick={() => prev && jump(prev.id)}
            title="AI 추정 위치를 한 줄 위로 맞추기"
          >
            ◀ 이전
          </button>
          <button
            className="ghost small"
            disabled={!next}
            onClick={() => next && jump(next.id)}
            title="AI 추정 위치를 한 줄 아래로 맞추기"
          >
            다음 ▶
          </button>
        </div>
      </header>
      <ol ref={listRef} className="script-list" onWheel={pauseFollowing} onTouchMove={pauseFollowing}>
        {cues.map((cue) => {
          const isCurrent = cue.id === currentId
          const isReturn = cue.id === returnId
          const classes = [
            'cue',
            `cue-${cue.type}`,
            isCurrent && 'cue-current',
            isCurrent && uncertain && 'cue-uncertain',
            isCurrent && paused && 'cue-paused',
            isReturn && 'cue-return',
          ]
            .filter(Boolean)
            .join(' ')

          return (
            <li
              key={cue.id}
              ref={(el) => {
                if (el) rowRefs.current.set(cue.id, el)
                else rowRefs.current.delete(cue.id)
              }}
              className={classes}
              aria-current={isCurrent ? 'true' : undefined}
              role="button"
              tabIndex={0}
              title="누르면 여기로 위치 맞추기"
              onClick={() => jump(cue.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') jump(cue.id)
              }}
            >
              <span className="cue-id">#{cue.id}</span>
              <span className="cue-text">
                {cue.type === 'lyric' && !cue.text.startsWith('♪') && <span aria-label="가사">♪ </span>}
                {cue.type !== 'dialogue' && cue.type !== 'lyric' && (
                  <span className="cue-type">{CUE_TYPE_LABEL[cue.type]}</span>
                )}
                {cue.text}
                {cue.speaker && <span className="cue-speaker">{cue.speaker}</span>}
              </span>
              <span className="cue-tags">
                {isReturn && <span className="cue-tag tag-return">복귀</span>}
                {isCurrent && confidence !== null && (
                  <span className="cue-tag">
                    {uncertain ? '불확실' : 'AI 추정 위치'} · 신뢰도 {confidence.toFixed(2)}
                  </span>
                )}
              </span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
