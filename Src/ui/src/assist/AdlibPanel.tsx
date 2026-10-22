// 애드리브 임시 자막. 대본을 벗어났을 때 오퍼레이터가 자막을 바로 만들어 송출한다.
//  ① 인식된 말: 이탈 뒤 들린 말을 모아 보여 주고, 고쳐서 송출할 수 있다 (고치기 시작하면 자동 갱신을 멈춤)
//  ② 직접 작성: 오퍼레이터가 처음부터 써서 송출
// 이탈 중에 자동으로 열리고, 쓰던 내용이 있으면 복귀해도 닫히지 않는다. 송출 판단은 오퍼레이터가 한다.

import { useState, type KeyboardEvent } from 'react'
import type { SubtitleSource } from '../protocol'
import { mergeTranscripts } from '../transcripts'
import type { RecognitionEntry } from '../useEngine'

/** 직접 열었을 때 몇 초 전 인식부터 채울지 */
const MANUAL_LOOKBACK_MS = 10_000

export interface SentSubtitle {
  at: number
  text: string
  source: SubtitleSource
}

interface Props {
  /** 지금 이탈 중이면 그 시작 시각, 아니면 null */
  deviationSince: number | null
  recognitionLog: RecognitionEntry[]
  sent: SentSubtitle[]
  onSend: (text: string, source: SubtitleSource) => void
}

const clock = (ms: number) =>
  new Date(ms).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })

const SOURCE_LABEL: Record<SubtitleSource, string> = { recognized: '인식 수정', manual: '직접 작성' }

export function AdlibPanel({ deviationSince, recognitionLog, sent, onSend }: Props) {
  const [openedAt, setOpenedAt] = useState<number | null>(null) // 직접 연 시각
  const [edited, setEdited] = useState<string | null>(null) // ①을 고치기 시작하면 고친 글자
  const [manual, setManual] = useState('')
  const [consumedAt, setConsumedAt] = useState(0) // ①을 송출할 때 마지막 인식 시각. 그 뒤 인식만 다시 모은다
  // 가장 최근 이탈 시작 시각. 복귀한 뒤에도 쓰던 내용을 이어 고칠 수 있게 기억한다
  const [lastSince, setLastSince] = useState<number | null>(null)
  if (deviationSince !== null && deviationSince !== lastSince) setLastSince(deviationSince)

  const active = deviationSince !== null
  const visible = active || openedAt !== null || edited !== null || manual.trim() !== ''

  if (!visible) {
    return (
      <section className="panel adlib adlib-closed">
        <h2>애드리브 임시 자막</h2>
        <button className="ghost small" onClick={() => setOpenedAt(Date.now())}>
          열기
        </button>
      </section>
    )
  }

  // 이탈 중이면 이탈 시작부터, 직접 열었으면 연 시각 조금 전부터 모은다
  const base = deviationSince ?? (openedAt !== null ? openedAt - MANUAL_LOOKBACK_MS : (lastSince ?? Infinity))
  const from = Math.max(base, consumedAt)
  const recognized = mergeTranscripts(recognitionLog.filter((e) => e.at > from).map((e) => e.transcript))
  const text1 = edited ?? recognized

  const send = (text: string, source: SubtitleSource) => {
    const line = text.trim()
    if (!line) return
    onSend(line, source)
    if (source === 'recognized') {
      setEdited(null)
      setConsumedAt(recognitionLog[recognitionLog.length - 1]?.at ?? 0)
    } else {
      setManual('')
    }
  }

  // 실수로 송출하지 않게 Enter는 줄바꿈, Ctrl+Enter 로 송출
  const onKey = (source: SubtitleSource, text: string) => (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      send(text, source)
    }
  }

  const close = () => {
    setOpenedAt(null)
    setEdited(null)
    setManual('')
  }

  return (
    <section className="panel adlib" aria-label="애드리브 임시 자막">
      <header className="adlib-head">
        <h2>
          애드리브 임시 자막 {active && <span className="adlib-live">이탈 중</span>}
        </h2>
        {!active && (
          <button className="ghost small" onClick={close}>
            닫기
          </button>
        )}
      </header>

      <div className="adlib-cols">
        <div className="adlib-col">
          <div className="adlib-label">
            <span>① 인식된 말 (고쳐서 송출)</span>
            {edited !== null && (
              <button className="ghost small" onClick={() => setEdited(null)}>
                최신 인식으로 다시 채우기
              </button>
            )}
          </div>
          <textarea
            value={text1}
            onChange={(e) => setEdited(e.target.value)}
            onKeyDown={onKey('recognized', text1)}
            placeholder="이탈 뒤 들린 말이 여기에 모입니다"
            rows={2}
          />
          <div className="adlib-actions">
            <span className="muted small">{edited !== null ? '수정 중 · 자동 갱신 멈춤' : '자동으로 채워지는 중'}</span>
            <button onClick={() => send(text1, 'recognized')} disabled={!text1.trim()}>
              송출
            </button>
          </div>
        </div>

        <div className="adlib-col">
          <div className="adlib-label">
            <span>② 직접 작성</span>
          </div>
          <textarea
            value={manual}
            onChange={(e) => setManual(e.target.value)}
            onKeyDown={onKey('manual', manual)}
            placeholder="자막을 직접 입력"
            rows={2}
          />
          <div className="adlib-actions">
            <span />
            <button onClick={() => send(manual, 'manual')} disabled={!manual.trim()}>
              송출
            </button>
          </div>
        </div>
      </div>

      {sent.length > 0 && (
        <ol className="adlib-sent">
          {[...sent]
            .reverse()
            .slice(0, 3)
            .map((s) => (
              <li key={s.at}>
                <time>{clock(s.at)}</time>
                <span className="adlib-src">{SOURCE_LABEL[s.source]}</span>
                <span className="adlib-text">{s.text}</span>
              </li>
            ))}
        </ol>
      )}
    </section>
  )
}
