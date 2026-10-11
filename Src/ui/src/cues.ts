// 자막 큐 데이터. 기준: 수행계획서 (6) 데이터 정의의 Cue.
// 정규화 본문은 엔진(① 큐 시트 로더)이 만들기 때문에 화면에서는 다루지 않는다.

export type CueType = 'dialogue' | 'lyric' | 'sound' | 'blackout' | 'notice'

export interface Cue {
  id: number
  order: number
  type: CueType
  speaker: string
  text: string
}

export const CUE_TYPE_LABEL: Record<CueType, string> = {
  dialogue: '대사',
  lyric: '가사',
  sound: '음향',
  blackout: '암전',
  notice: '안내',
}

const TYPE_ALIASES: Record<string, CueType> = {
  dialogue: 'dialogue', 대사: 'dialogue',
  lyric: 'lyric', 가사: 'lyric',
  sound: 'sound', 음향: 'sound',
  blackout: 'blackout', 암전: 'blackout',
  notice: 'notice', 안내: 'notice',
}

/** 큐 CSV 열 (임시). 데이터 담당과 열이 확정되면 여기를 고친다. */
export const CUE_CSV_COLUMNS = ['id', 'order', 'type', 'speaker', 'text'] as const

/** 따옴표("...")와 줄바꿈이 들어간 칸까지 처리하는 CSV 파서 */
export function parseCsv(source: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  const text = source.replace(/^﻿/, '')

  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        field += '"'
        i++
      } else if (ch === '"') {
        quoted = false
      } else {
        field += ch
      }
    } else if (ch === '"') {
      quoted = true
    } else if (ch === ',') {
      row.push(field)
      field = ''
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++
      row.push(field)
      rows.push(row)
      row = []
      field = ''
    } else {
      field += ch
    }
  }
  if (field !== '' || row.length > 0) {
    row.push(field)
    rows.push(row)
  }
  return rows.filter((r) => r.some((cell) => cell.trim() !== ''))
}

/** 큐 CSV를 읽어 Cue 목록으로. 형식이 틀리면 줄 번호와 함께 Error를 던진다. */
export function parseCueCsv(source: string): Cue[] {
  const [header, ...body] = parseCsv(source)
  if (!header) throw new Error('빈 파일입니다.')

  const index = Object.fromEntries(header.map((name, i) => [name.trim(), i]))
  const missing = CUE_CSV_COLUMNS.filter((name) => !(name in index))
  if (missing.length > 0) {
    throw new Error(`필요한 열이 없습니다: ${missing.join(', ')}`)
  }

  return body
    .map((cells, i) => {
      const line = i + 2
      const get = (name: (typeof CUE_CSV_COLUMNS)[number]) => (cells[index[name]] ?? '').trim()
      const id = Number(get('id'))
      const order = Number(get('order'))
      const type = TYPE_ALIASES[get('type')]
      if (!Number.isInteger(id)) throw new Error(`${line}번째 줄: id가 숫자가 아닙니다.`)
      if (!Number.isInteger(order)) throw new Error(`${line}번째 줄: order가 숫자가 아닙니다.`)
      if (!type) throw new Error(`${line}번째 줄: 알 수 없는 유형 "${get('type')}"`)
      return { id, order, type, speaker: get('speaker'), text: get('text') }
    })
    .sort((a, b) => a.order - b.order)
}
