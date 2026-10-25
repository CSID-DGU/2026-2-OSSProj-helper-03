// 테스트용 대사 입력. '대사 입력' 모드에서 입력한 글자를 음성인식 결과 한 번으로 엔진에 보낸다.
// 녹음·마이크·음성인식 키 없이 위치 추적과 이탈 알림을 확인하기 위한 것.

import { useState, type FormEvent } from 'react'
import type { Cue } from '../cues'

interface Props {
  cues: Cue[]
  currentId: number | null
  onSay: (text: string) => void
}

/** 현재 위치 다음의 대사·가사 큐. 아직 위치가 없으면 첫 대사 */
function nextSpoken(cues: Cue[], currentId: number | null): Cue | undefined {
  const spoken = cues.filter((c) => c.type === 'dialogue' || c.type === 'lyric')
  if (currentId === null) return spoken[0]
  const order = cues.find((c) => c.id === currentId)?.order ?? -Infinity
  return spoken.find((c) => c.order > order)
}

export function TestInput({ cues, currentId, onSay }: Props) {
  const [text, setText] = useState('')
  const next = nextSpoken(cues, currentId)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const line = text.trim()
    if (!line) return
    onSay(line)
    setText('')
  }

  return (
    <form className="panel test-input" onSubmit={submit}>
      <div className="test-row">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="배우가 한 말을 입력하고 Enter"
          aria-label="테스트 대사 입력"
        />
        <button type="submit" disabled={!text.trim()}>
          보내기
        </button>
        <button type="button" className="ghost" disabled={!next} onClick={() => next && setText(next.text)}>
          다음 대사 채우기{next ? ` (#${next.id})` : ''}
        </button>
      </div>
      <p className="muted small">
        대본에 없는 말을 치면 애드리브, 몇 줄 건너뛰면 누락, 앞 대사를 다시 치면 반복으로 처리됩니다.
      </p>
    </form>
  )
}
