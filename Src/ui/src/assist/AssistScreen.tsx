// ② 보조 화면 (공연 중, 보기 전용). 기준: 수행계획서 그림 4 보조 화면 와이어프레임.
// 대본 큐 송출 기능은 두지 않는다 (요구사항 R3). 애드리브 임시 자막만 오퍼레이터가 확인해서 송출한다 (팀 합의 필요).
// 위치 맞추기(대본 줄 클릭 · 이전/다음)는 송출이 아니라 엔진의 AI 추정 위치만 고친다.

import { useMemo, useState } from 'react'
import type { Cue } from '../cues'
import type { InputMode, SubtitleSource } from '../protocol'
import { RETURN_HIGHLIGHT_MS, STALE_MS } from '../settings'
import type { EngineState } from '../useEngine'
import { useNow } from '../useNow'
import { formatElapsed } from '../time'
import { AdlibPanel, type SentSubtitle } from './AdlibPanel'
import { AudioPlayer } from './AudioPlayer'
import { DeviationCard, type HoldReason } from './DeviationCard'
import { DeviationTimeline } from './DeviationTimeline'
import { EdgeFlash } from './EdgeFlash'
import { PhonePreview } from './PhonePreview'
import { RecognitionLog } from './RecognitionLog'
import { ScriptList } from './ScriptList'
import { TestInput } from './TestInput'
import './assist.css'

const INPUT_LABEL: Record<InputMode, string> = { file: '음성 파일', mic: '마이크', text: '대사 입력 (테스트)' }

interface Props {
  showName: string
  cues: Cue[]
  input: InputMode
  /** 회차 시작 시각 (epoch ms) */
  startedAt: number
  engine: EngineState
  threshold: number
  onEnd: () => void
  /** 대사 입력 모드에서 입력한 대사를 보냄 */
  onSay: (text: string) => void
  /** 애드리브 임시 자막 송출 */
  onSendSubtitle: (text: string, source: SubtitleSource) => void
  /** 위치 맞추기: AI 추정 위치를 이 큐로 */
  onJump: (cueId: number) => void
}

export function AssistScreen(props: Props) {
  const { showName, cues, input: inputMode, startedAt, engine, threshold, onEnd, onSay, onSendSubtitle, onJump } = props
  const now = useNow()
  const [sent, setSent] = useState<SentSubtitle[]>([])
  const cueById = useMemo(() => new Map(cues.map((c) => [c.id, c])), [cues])
  const { position, deviation, deviationAt, deviationLog, recognitionLog, input, connection, lastMessageAt } = engine

  const stale = connection === 'open' && lastMessageAt !== null && now - lastMessageAt > STALE_MS
  const noInput = input !== null && input.audio_level === 0
  const song = input?.segment === 'song'

  const hold: HoldReason =
    connection !== 'open' ? 'disconnected' : stale ? 'stale' : noInput ? 'no-input' : song ? 'song' : null

  const deviating = deviation !== null && deviation.return_cue_id === null

  const sendSubtitle = (text: string, source: SubtitleSource) => {
    onSendSubtitle(text, source)
    setSent((list) => [...list, { at: Date.now(), text, source }])
  }

  // 휴대폰 미리보기: 지금 큐로 온 뒤에 임시 자막을 송출했으면 그것을 보여 준다
  const cueSince = useMemo(() => {
    let since = 0
    for (let i = recognitionLog.length - 1; i >= 0 && recognitionLog[i].cueId === position?.cue_id; i--) {
      since = recognitionLog[i].at
    }
    return since
  }, [recognitionLog, position?.cue_id])
  const lastSent = sent[sent.length - 1]
  const tempSubtitle = lastSent && lastSent.at >= cueSince ? lastSent.text : undefined

  const returnId =
    deviation?.return_cue_id != null && deviationAt !== null && now - deviationAt < RETURN_HIGHLIGHT_MS
      ? deviation.return_cue_id
      : null

  return (
    <div className="assist">
      <EdgeFlash deviation={deviation} />
      <header className="assist-head">
        <div className="title">
          <h1 className="show-name">{showName}</h1>
          <span className="elapsed" title="회차를 시작한 뒤 흐른 시간">
            {formatElapsed(now - startedAt)}
          </span>
          <span className="mode-label">{INPUT_LABEL[inputMode]}</span>
        </div>
        <div className="status">
          {inputMode === 'file' && <AudioPlayer session={startedAt} engineSec={input?.audio_sec ?? null} />}
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
          paused={noInput}
          onJump={onJump}
        />

        {/* 오른쪽: 위에서부터 알림 → 애드리브 임시 자막 → 휴대폰 미리보기 → 이탈 기록. 순서가 바뀌지 않게 고정 */}
        <div className="side">
          <DeviationCard deviation={deviation} deviationAt={deviationAt} hold={hold} cueById={cueById} now={now} />
          <AdlibPanel
            deviationSince={deviating && deviation ? deviation.since : null}
            recognitionLog={recognitionLog}
            sent={sent}
            onSend={sendSubtitle}
          />
          <PhonePreview
            cue={position ? cueById.get(position.cue_id) : undefined}
            deviating={deviating}
            temp={tempSubtitle}
          />
          <DeviationTimeline log={deviationLog} now={now} />
        </div>
      </div>

      {/* 아래: 팀용 도구 (테스트 입력 · 성능 확인). 오퍼레이터 화면과 구분되게 얇게 */}
      <div className="team-tools">
        {inputMode === 'text' && <TestInput cues={cues} currentId={position?.cue_id ?? null} onSay={onSay} />}
        <RecognitionLog entries={recognitionLog} cueById={cueById} startedAt={startedAt} threshold={threshold} />
      </div>
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
