/** Canonical UTF-8 hashes match Artifact Store serialization, including Unicode keys. */
function compareScalars(left: string, right: string): number {
  const a = Array.from(left), b = Array.from(right)
  for (let index = 0; index < Math.min(a.length, b.length); index++) {
    const difference = a[index].codePointAt(0)! - b[index].codePointAt(0)!
    if (difference) return difference
  }
  return a.length - b.length
}
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']'
  if (value !== null && typeof value === 'object') {
    const object = value as Record<string, unknown>
    return '{' + Object.keys(object).sort(compareScalars).map(key => JSON.stringify(key) + ':' + canonicalJson(object[key])).join(',') + '}'
  }
  return JSON.stringify(value)
}
export async function hashUtf8(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
}
