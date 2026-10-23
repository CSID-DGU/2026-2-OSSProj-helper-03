// 임시 시작 패널. 준비 화면(그림 5)을 만들기 전까지 공연 이름과 큐 파일만 받아 회차를 시작한다.
// 마지막으로 시작한 설정(공연 이름 · 큐 파일 내용 · 소리 입력)을 브라우저에 기억해 다음에 다시 채운다
// (회차를 끝내고 돌아올 때마다 샘플 대본으로 돌아가 다른 대본으로 시작하던 실수 방지).

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

const SAMPLE = { name: '샘플 공연', cueFile: 'sample_cues.csv', csv: sampleCsv, input: 'file' as InputMode }
const STORAGE_KEY = 'helper.start'

interface Saved {
  name: string
  cueFile: string
  csv: string
  input: InputMode
}

/** 지난번 설정. 없거나 읽을 수 없으면(사생활 보호 모드 등) 샘플 */
function loadSaved(): Saved {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as Saved | null
    if (saved && saved.csv && saved.cueFile) {
      parseCueCsv(saved.csv)   // 형식이 깨졌으면 샘플로
      return saved
    }
  } catch {
    // 저장 안 됨 · 깨진 값: 샘플로 시작
  }
  return SAMPLE
}

function save(value: Saved) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
  } catch {
    // 저장이 막혀 있어도 회차 시작에는 지장 없음
  }
}

interface Props {
  connection: Connection
  onStart: (show: { name: string; cueFile: string; cues: Cue[]; input: InputMode }) => void
}

export function StartPanel({ connection, onStart }: Props) {
  const [initial] = useState(loadSaved)
  const [name, setName] = useState(initial.name)
  const [cueFile, setCueFile] = useState(initial.cueFile)
  const [csv, setCsv] = useState(initial.csv)
  const [cues, setCues] = useState<Cue[]>(() => parseCueCsv(initial.csv))
  const [error, setError] = useState<string | null>(null)
  const [input, setInput] = useState<InputMode>(initial.input)

  const applyCsv = (fileName: string, text: string) => {
    setCues(parseCueCsv(text))
    setCueFile(fileName)
    setCsv(text)
    setError(null)
  }

  const loadFile = async (file: File | undefined) => {
    if (!file) return
    try {
      applyCsv(file.name, await file.text())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const start = () => {
    save({ name: name.trim(), cueFile, csv, input })
    onStart({ name: name.trim(), cueFile, cues, input })
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
      <p className={error ? 'error' : 'muted'}>
        {error ?? `${cueFile} · 큐 ${cues.length}개`}
        {!error && cueFile !== SAMPLE.cueFile && (
          <button className="link small" onClick={() => applyCsv(SAMPLE.cueFile, SAMPLE.csv)}>
            샘플 대본으로
          </button>
        )}
      </p>

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
          실서버 · 모의 서버 모두 이 선택을 따릅니다. 음성 파일은 큐 파일과 같은 폴더의 녹음(또는 서버의 HELPER_AUDIO_FILE)을
          재생합니다.
        </p>
      </fieldset>

      <button
        disabled={connection !== 'open' || cues.length === 0 || name.trim() === ''}
        onClick={start}
      >
        보조 화면 시작
      </button>
      <p className="muted small">준비 화면이 만들어지면 이 패널은 준비 화면으로 바뀝니다.</p>
    </main>
  )
}
