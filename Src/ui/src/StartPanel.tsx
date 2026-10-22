// 임시 시작 패널. 준비 화면(그림 5)을 만들기 전까지 공연 이름과 큐 파일만 받아 회차를 시작한다.

import { useState } from 'react'
import sampleCsv from '../mock/sample_cues.csv?raw'
import { parseCueCsv, type Cue } from './cues'
import type { InputMode } from './protocol'
import { ENGINE_URL, type Connection } from './useEngine'

const CONNECTION_LABEL: Record<Connection, string> = {
  connecting: '연결 중',
  open: '연결됨',
  closed: '끊김 (다시 연결하는 중)',
}

const INPUT_OPTIONS: { mode: InputMode; label: string; hint: string }[] = [
  { mode: 'file', label: '음성 파일', hint: '녹음 파일을 실제 시간 속도로 재생하며 추적' },
  { mode: 'mic', label: '마이크', hint: '마이크로 들어오는 소리를 추적' },
  { mode: 'text', label: '대사 입력 (테스트)', hint: '대사를 직접 입력하면 인식 결과로 보고 추적. 녹음·마이크 없이 확인용' },
]

interface Props {
  connection: Connection
  onStart: (show: { name: string; cueFile: string; cues: Cue[]; input: InputMode }) => void
}

export function StartPanel({ connection, onStart }: Props) {
  const [name, setName] = useState('샘플 공연')
  const [cueFile, setCueFile] = useState('sample_cues.csv')
  const [cues, setCues] = useState<Cue[]>(() => parseCueCsv(sampleCsv))
  const [error, setError] = useState<string | null>(null)
  const [input, setInput] = useState<InputMode>('file')

  const loadFile = async (file: File | undefined) => {
    if (!file) return
    try {
      setCues(parseCueCsv(await file.text()))
      setCueFile(file.name)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <main className="start">
      <h1>회차 시작</h1>
      <p className="muted">
        엔진 {ENGINE_URL} · <span className={`conn conn-${connection}`}>{CONNECTION_LABEL[connection]}</span>
      </p>

      <label>
        공연 이름
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>

      <label>
        자막 큐 파일 (CSV)
        <input type="file" accept=".csv,text/csv" onChange={(e) => loadFile(e.target.files?.[0])} />
      </label>
      <p className={error ? 'error' : 'muted'}>{error ?? `${cueFile} · 큐 ${cues.length}개`}</p>

      <fieldset className="modes">
        <legend>소리 입력</legend>
        {INPUT_OPTIONS.map((opt) => (
          <label key={opt.mode} className="mode">
            <input
              type="radio"
              name="input"
              value={opt.mode}
              checked={input === opt.mode}
              onChange={() => setInput(opt.mode)}
            />
            <span>
              {opt.label}
              <span className="muted small">{opt.hint}</span>
            </span>
          </label>
        ))}
        <p className="muted small">
          모의 서버는 이 선택을 따릅니다. 실서버는 아직 서버 설정(.env의 HELPER_INPUT)을 따르고, 대사 입력은 지원하지
          않습니다.
        </p>
      </fieldset>

      <button
        disabled={connection !== 'open' || cues.length === 0 || name.trim() === ''}
        onClick={() => onStart({ name: name.trim(), cueFile, cues, input })}
      >
        보조 화면 시작
      </button>
      <p className="muted small">준비 화면이 만들어지면 이 패널은 준비 화면으로 바뀝니다.</p>
    </main>
  )
}
