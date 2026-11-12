// ② 보조 화면 (공연 중, 보기 전용). 기준: 수행계획서 그림 4 보조 화면 와이어프레임.
// 대본 큐 송출 기능은 두지 않는다 (요구사항 R3). 애드리브 임시 자막만 오퍼레이터가 확인해서 송출한다 (팀 합의 필요).
// 위치 맞추기(대본 줄 클릭 · 이전/다음)는 송출이 아니라 엔진의 AI 추정 위치만 고친다.

import { useMemo, useState } from 'react'
import type { Cue } from '../cues'
import type { InputMode, SubtitleSource } from '../protocol'
import { RETURN_HIGHLIGHT_MS, STALE_MS } from '../settings'
import type { EngineState } from '../useEngine'
import { useNow } from '../useNow'
import { shortFollowers } from '../shortLines'
import { formatElapsed } from '../time'
import { AdlibPanel, type SentSubtitle } from './AdlibPanel'
import { AudioPlayer } from './AudioPlayer'
import { DeviationCard, type HoldReason } from './DeviationCard'
import { DeviationTimeline } from './DeviationTimeline'
import { EdgeFlash } from './EdgeFlash'
import { PhonePreview } from './PhonePreview'
import { RecognitionLog } from './RecognitionLog'
import { SendPanel } from './SendPanel'
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
  /** 대본 큐 송출 (오퍼레이터가 확인하고 누름) */
  onSendCue: (cueId: number, groupedIds: number[]) => void
}

export function AssistScreen(props: Props) {
  const { showName, cues, input: inputMode, startedAt, engine, threshold, onEnd, onSay, onSendSubtitle, onJump, onSendCue } = props
  const now = useNow()
  const [sent, setSent] = useState<SentSubtitle[]>([])
  /** 마지막으로 송출한 대본 큐 */
  const [sentCue, setSentCue] = useState<{ id: number; grouped: number[]; at: number } | null>(null)
  /** 닫은 엔진 오류 (받은 시각). 같은 오류는 다시 띄우지 않는다 */
  const [dismissedErrorAt, setDismissedErrorAt] = useState<number | null>(null)
  const cueById = useMemo(() => new Map(cues.map((c) => [c.id, c])), [cues])
  const { position, deviation, deviationAt, deviationLog, recognitionLog, input, connection, lastMessageAt, error } = engine
  const shownError = error && error.at !== dismissedErrorAt ? error : null

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

  // 짧은 대사 묶어 보이기: 지금 줄 바로 뒤의 짧은 대사들
  const followers = useMemo(() => shortFollowers(cues, position?.cue_id ?? null), [cues, position?.cue_id])

  const returnId =
    deviation?.return_cue_id != null && deviationAt !== null && now - deviationAt < RETURN_HIGHLIGHT_MS
      ? deviation.return_cue_id
      : null

  // 송출 칸: AI 추천 큐 (복귀 직후면 복귀 큐). 송출은 오퍼레이터가 확인하고 누른다
  const suggestId = returnId ?? position?.cue_id ?? null
  const suggestFollowers = useMemo(() => shortFollowers(cues, suggestId), [cues, suggestId])
  const sendCue = (cue: Cue) => {
    const grouped = suggestFollowers.map((f) => f.id)
    onSendCue(cue.id, grouped)
    setSentCue({ id: cue.id, grouped, at: Date.now() })
  }

  // 휴대폰 미리보기: 가장 마지막에 송출한 것 (대본 큐 또는 애드리브 임시 자막)
  const lastTemp = sent[sent.length - 1]
  const showTemp = lastTemp && (!sentCue || lastTemp.at > sentCue.at)

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
        {shownError && (
          <div className="engine-error" role="alert">
            <span>
              {shownError.during === 'session.start' ? '회차를 시작하지 못했습니다' : '음성인식 오류'} · {shownError.message}
            </span>
            {shownError.during === 'session.start' ? (
              <button className="small" onClick={onEnd}>
                시작 화면으로
              </button>
            ) : (
              <button className="ghost small" onClick={() => setDismissedErrorAt(shownError.at)}>
                닫기
              </button>
            )}
          </div>
        )}
      </header>

      <div className="assist-body">
        <ScriptList
          cues={cues}
          currentId={position?.cue_id ?? null}
          confidence={position?.confidence ?? null}
          threshold={threshold}
          returnId={returnId}
          paused={noInput}
          followerIds={followers.map((f) => f.id)}
          sentIds={sentCue ? [sentCue.id, ...sentCue.grouped] : []}
          onJump={onJump}
        />

        {/* 오른쪽: 위에서부터 알림 → 자막 송출 → 애드리브 임시 자막 → 휴대폰 미리보기 → 이탈 기록. 순서 고정 */}
        <div className="side">
          <DeviationCard deviation={deviation} deviationAt={deviationAt} hold={hold} cueById={cueById} now={now} />
          <SendPanel
            cue={suggestId !== null ? cueById.get(suggestId) : undefined}
            followers={suggestFollowers}
            sentId={sentCue?.id ?? null}
            deviating={deviating}
            onSend={sendCue}
          />
          <AdlibPanel
            deviationSince={deviating && deviation ? deviation.since : null}
            recognitionLog={recognitionLog}
            sent={sent}
            onSend={sendSubtitle}
          />
          <PhonePreview
            cue={!showTemp && sentCue ? cueById.get(sentCue.id) : undefined}
            followers={!showTemp && sentCue ? sentCue.grouped.flatMap((id) => cueById.get(id) ?? []) : []}
            temp={showTemp ? lastTemp.text : undefined}
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
