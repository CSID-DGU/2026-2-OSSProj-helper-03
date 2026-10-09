// ② 보조 화면 (공연 중, 보기 전용). 기준: 수행계획서 그림 4 보조 화면 와이어프레임.
// 이 화면에는 송출 기능을 두지 않는다 (요구사항 R3).

import { useMemo } from 'react'
import type { Cue } from '../cues'
import { RETURN_HIGHLIGHT_MS, STALE_MS } from '../settings'
import type { EngineState } from '../useEngine'
import { useNow } from '../useNow'
import { DeviationCard, type HoldReason } from './DeviationCard'
import { DeviationTimeline } from './DeviationTimeline'
import { EdgeFlash } from './EdgeFlash'
import { ScriptList } from './ScriptList'
import './assist.css'

interface Props {
  showName: string
  cues: Cue[]
  engine: EngineState
  threshold: number
  onEnd: () => void
}

export function AssistScreen({ showName, cues, engine, threshold, onEnd }: Props) {
  const now = useNow()
  const cueById = useMemo(() => new Map(cues.map((c) => [c.id, c])), [cues])
  const { position, deviation, deviationAt, deviationLog, input, connection, lastMessageAt } = engine

  const stale = connection === 'open' && lastMessageAt !== null && now - lastMessageAt > STALE_MS
  const noInput = input !== null && input.audio_level === 0
  const song = input?.segment === 'song'

  const hold: HoldReason =
    connection !== 'open' ? 'disconnected' : stale ? 'stale' : noInput ? 'no-input' : song ? 'song' : null

  const returnId =
    deviation?.return_cue_id != null && deviationAt !== null && now - deviationAt < RETURN_HIGHLIGHT_MS
      ? deviation.return_cue_id
      : null

  return (
    <div className="assist">
      <EdgeFlash deviation={deviation} />
      <header className="assist-head">
        <h1 className="show-name">{showName}</h1>
        <div className="status">
          <InputBadge hold={hold} level={input?.audio_level ?? null} />
          <span className={`badge ${song ? 'badge-song' : ''}`}>{song ? '노래 구간' : '대사 구간'}</span>
          {position && <span className="latency">지연 {(position.latency_ms / 1000).toFixed(1)}초</span>}
          <button className="ghost small" onClick={onEnd}>
            회차 종료
          </button>
        </div>
      </header>

      <div className="assist-body">
        <ScriptList
          cues={cues}
          currentId={position?.cue_id ?? null}
          confidence={position?.confidence ?? null}
          threshold={threshold}
          returnId={returnId}
          paused={song || noInput}
        />

        <div className="side">
          <DeviationCard deviation={deviation} deviationAt={deviationAt} hold={hold} cueById={cueById} now={now} />
          <DeviationTimeline log={deviationLog} now={now} />
          <ul className="notes">
            <li>일치 점수가 기준({threshold.toFixed(2)}) 미만이면 알림을 띄우지 않습니다.</li>
            <li>노래 구간·음향 입력 끊김 시 추적을 멈추고 상태만 표시합니다.</li>
            <li>이 화면에는 송출 버튼이 없습니다. 송출은 기존 프로그램에서 하세요.</li>
          </ul>
        </div>
      </div>

      <section className="panel transcript">
        <h2>인식 글자 (확인용)</h2>
        <p>{position?.transcript ? `… ${position.transcript} …` : '—'}</p>
      </section>
    </div>
  )
}

function InputBadge({ hold, level }: { hold: HoldReason; level: number | null }) {
  if (hold === 'disconnected') return <span className="badge badge-error">엔진 연결 끊김</span>
  if (hold === 'stale') return <span className="badge badge-error">엔진 응답 없음</span>
  if (level === null) return <span className="badge">입력 대기</span>
  if (level === 0) return <span className="badge badge-warn">음향 입력 없음</span>
  return (
    <span className="badge badge-ok">
      음향 입력 정상
      <span className="level" aria-hidden>
        <span style={{ width: `${Math.round(level * 100)}%` }} />
      </span>
    </span>
  )
}
