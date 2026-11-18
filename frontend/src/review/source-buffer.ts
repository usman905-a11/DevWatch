export interface CoveredRange {
  startLine: number
  endLine: number
}

export interface ExcerptBuffer {
  isFullFile: boolean
  coveredRanges: CoveredRange[]
  lines: string[]
  content: string
}

function mergeRanges(ranges: CoveredRange[]): CoveredRange[] {
  if (ranges.length <= 1) return ranges
  const sorted = [...ranges].sort((a, b) => a.startLine - b.startLine || a.endLine - b.endLine)
  const merged: CoveredRange[] = [sorted[0]]
  for (let i = 1; i < sorted.length; i++) {
    const prev = merged[merged.length - 1]
    const curr = sorted[i]
    if (curr.startLine <= prev.endLine + 1) {
      merged[merged.length - 1] = {
        startLine: prev.startLine,
        endLine: Math.max(prev.endLine, curr.endLine),
      }
    } else {
      merged.push(curr)
    }
  }
  return merged
}

export function mergeSourceExcerpt(
  prev: ExcerptBuffer | null,
  excerpt: { startLine: number; endLine: number; data: string },
  isFullFile = false,
): ExcerptBuffer {
  const newLines = excerpt.data.split('\n')
  if (isFullFile) {
    return {
      isFullFile: true,
      coveredRanges: [{ startLine: 1, endLine: Math.max(1, newLines.length) }],
      lines: newLines,
      content: excerpt.data,
    }
  }
  const startLine = Math.max(1, excerpt.startLine)
  const effectiveEnd = Math.max(excerpt.endLine, startLine + newLines.length - 1)
  const lines = prev ? [...prev.lines] : []
  const requiredLength = startLine - 1 + newLines.length
  while (lines.length < requiredLength) {
    lines.push('')
  }
  for (let i = 0; i < newLines.length; i++) {
    lines[startLine - 1 + i] = newLines[i]
  }
  const coveredRanges = mergeRanges([
    ...(prev?.coveredRanges ?? []),
    { startLine, endLine: effectiveEnd },
  ])
  return {
    isFullFile: false,
    coveredRanges,
    lines,
    content: lines.join('\n'),
  }
}

export function isRangeCoveredByTab(
  buffer: ExcerptBuffer | null | undefined,
  range?: { startLine: number; endLine: number } | null,
): boolean {
  if (!buffer) return false
  if (buffer.isFullFile) return true
  if (!range) return buffer.coveredRanges.length > 0
  const start = Math.max(1, range.startLine)
  const end = Math.max(start, range.endLine)
  return buffer.coveredRanges.some(covered => covered.startLine <= start && covered.endLine >= end)
}

