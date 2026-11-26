// ② 보조 화면 (공연 중, 보기 전용). 기준: 수행계획서 그림 4 보조 화면 와이어프레임.
// 송출은 AI가 추천한 큐 · 애드리브 임시 자막을 오퍼레이터가 확인하고 직접 한다 (자동 송출 없음, 요구사항 R3).
// 위치 맞추기(대본 줄 클릭 · 이전/다음)는 송출이 아니라 엔진의 AI 추정 위치만 고친다.

import { useMemo, useState } from 'react'
import type { Cue } from '../cues'
import { INPUT_LABEL, type InputChoice } from '../inputs'
import type { SubtitleSource } from '../protocol'
import { PASSED_MAX_SHOWN, RETURN_HIGHLIGHT_MS, STALE_MS } from '../settings'
import type { EngineState } from '../useEngine'
import { useBrightness } from '../useBrightness'
import { useNow } from '../useNow'
import { shortFollowers } from '../shortLines'
import { formatElapsed } from '../time'
import { AdlibPanel, type SentSubtitle } from './AdlibPanel'
import { AudioPlayer } from './AudioPlayer'
import { BrightnessButton, DimLayer } from './Brightness'
import { DeviationCard, type HoldReason } from './DeviationCard'
import { DeviationTimeline } from './DeviationTimeline'
import { EdgeFlash } from './EdgeFlash'
import { PhonePreview } from './PhonePreview'
import { RecognitionLog } from './RecognitionLog'
import { SendPanel } from './SendPanel'
import { ScriptList } from './ScriptList'
import { TestInput } from './TestInput'
import './assist.css'

const ERROR_HEADLINE = {
  'session.start': '회차를 시작하지 못했습니다',
  recognize: '음성인식 오류',
  limit: '사용 시간이 끝났습니다',
} as const

interface Props {
  showName: string
  cues: Cue[]
  input: InputChoice
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
  /** 대본 큐 송출 (오퍼레이터가 확인하고 누름). 관객 화면은 신호 하나에 한 줄이라 한 번에 한 줄 */
  onSendCue: (cueId: number) => void
}

export function AssistScreen(props: Props) {
  const { showName, cues, input: inputMode, startedAt, engine, threshold, onEnd, onSay, onSendSubtitle, onJump, onSendCue } = props
  const now = useNow()
  const brightness = useBrightness()
  const [sent, setSent] = useState<SentSubtitle[]>([])
  /** 마지막으로 송출한 대본 큐 */
  const [sentCue, setSentCue] = useState<{ id: number; at: number } | null>(null)
  /** 이번 회차에 송출한 대본 큐 전부 */
  const [sentIds, setSentIds] = useState<number[]>([])
  /** 닫은 엔진 오류 (받은 시각). 같은 오류는 다시 띄우지 않는다 */
  const [dismissedErrorAt, setDismissedErrorAt] = useState<number | null>(null)
  const cueById = useMemo(() => new Map(cues.map((c) => [c.id, c])), [cues])
  const { position, passedIds, deviation, deviationAt, deviationLog, recognitionLog, input, connection, lastMessageAt, error } =
    engine
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

  // 곧 나올 짧은 줄: 지금 줄 바로 뒤의 짧은 대사들 (대본 목록에 '곧 나옴' 표시)
  const followers = useMemo(() => shortFollowers(cues, position?.cue_id ?? null), [cues, position?.cue_id])

  const returnId =
    deviation?.return_cue_id != null && deviationAt !== null && now - deviationAt < RETURN_HIGHLIGHT_MS
      ? deviation.return_cue_id
      : null

  // 송출 칸: AI 추천 큐 (복귀 직후면 복귀 큐). 송출은 오퍼레이터가 확인하고 누른다
  const suggestId = returnId ?? position?.cue_id ?? null
  // 곧 나올 짧은 줄: 1초도 안 되는 짧은 대사는 AI 추정이 건너뛰기 쉬워서 송출 칸에 미리 보여 주고 줄마다 따로 송출한다
  const suggestFollowers = useMemo(() => shortFollowers(cues, suggestId), [cues, suggestId])
  // 지나간 줄: AI 추정이 지금 줄로 오면서 화면에 안 띄운 줄 (엔진이 말한 것으로 본 줄). 송출 칸에 참고로만 보여 준다
  // (이미 말한 줄이라 관객 화면에는 보내지 않음). 복귀 큐를 추천할 때는 쓰지 않고, 이미 송출한 줄은 뺀다
  const suggestPassed = useMemo(
    () =>
      suggestId !== null && suggestId === position?.cue_id
        ? passedIds
            .filter((id) => !sentIds.includes(id))
            .slice(-PASSED_MAX_SHOWN)
            .flatMap((id) => cueById.get(id) ?? [])
        : [],
    [suggestId, position?.cue_id, passedIds, sentIds, cueById],
  )
  // 송출: 추천 큐, 곧 나올 짧은 줄, 다음 상황 자막 모두 누른 줄 하나만 보낸다
  const sendCue = (cue: Cue) => {
    onSendCue(cue.id)
    setSentCue({ id: cue.id, at: Date.now() })
    setSentIds((ids) => [...ids, cue.id])
  }

  // 다음 상황 자막: 추천 큐 바로 뒤의 상황 설명 줄(음향 · 암전 · 안내) 중 아직 송출하지 않은 첫 줄. 다음 대사 · 가사가 나오면 멈춘다
  const nextDesc = useMemo(() => {
    const at = cues.findIndex((c) => c.id === suggestId)
    if (at < 0) return undefined
    for (const cue of cues.slice(at + 1)) {
      if (cue.type === 'dialogue' || cue.type === 'lyric') return undefined
      if (!sentIds.includes(cue.id)) return cue
    }
    return undefined
  }, [cues, suggestId, sentIds])

  // 휴대폰 미리보기: 가장 마지막에 송출한 것 (대본 큐 또는 애드리브 임시 자막)
  const lastTemp = sent[sent.length - 1]
  const showTemp = lastTemp && (!sentCue || lastTemp.at > sentCue.at)

  return (
    <div className="assist">
      <EdgeFlash deviation={deviation} />
      <DimLayer level={brightness.level} />
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
          <BrightnessButton level={brightness.level} onNext={brightness.next} />
          <button className="ghost small" onClick={onEnd}>
            회차 종료
          </button>
        </div>
        {shownError && (
          <div className="engine-error" role="alert">
            <span>
              {ERROR_HEADLINE[shownError.during]} · {shownError.message}
            </span>
            {shownError.during !== 'recognize' ? (
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
          sentIds={sentIds}
          onJump={onJump}
        />

        {/* 오른쪽: 위에서부터 알림 → 자막 송출 → 애드리브 임시 자막 → 휴대폰 미리보기 → 이탈 기록. 순서 고정 */}
        <div className="side">
          <DeviationCard deviation={deviation} deviationAt={deviationAt} hold={hold} cueById={cueById} now={now} />
          <SendPanel
            cue={suggestId !== null ? cueById.get(suggestId) : undefined}
            followers={suggestFollowers}
            passed={suggestPassed}
            desc={nextDesc}
            sentIds={sentIds}
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
