import { describe, it, expect } from 'vitest'
import { mapIssuesToFindings } from '../App'
import { CodeIssue } from '../types'

describe('Report-only finding data flow', () => {
  it('mapIssuesToFindings correctly preserves replacement_code and backend fields', () => {
    const rawBackendIssues: CodeIssue[] = [
      {
        finding_id: 'find_123',
        file_path: 'app.py',
        line_number: 15,
        severity: 'HIGH',
        category: 'Security',
        title: 'SQL Injection',
        description: 'Vulnerable SQL query string formatting',
        suggestion: 'Wrap call in try-except block',
        replacement_code: 'cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))',
        cwe_id: 'CWE-89',
        confidence_score: 0.95,
      },
    ]

    const mappedFindings = mapIssuesToFindings(rawBackendIssues)

    expect(mappedFindings.length).toBe(1)
    expect(mappedFindings[0].id).toBe('find_123')
    expect(mappedFindings[0].suggestion).toBe('Wrap call in try-except block')
    expect(mappedFindings[0].replacement_code).toBe(
      'cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))'
    )
    expect(mappedFindings[0].cwe_id).toBe('CWE-89')
  })

  it('verifies prose suggestion is distinct from replacement_code', () => {
    const issueWithProseAndCode: CodeIssue = {
      finding_id: 'find_456',
      file_path: 'auth.py',
      line_number: 42,
      severity: 'CRITICAL',
      category: 'Security',
      title: 'Hardcoded Secret',
      description: 'Found hardcoded secret key',
      suggestion: 'Use environment variable instead of plain string',
      replacement_code: 'SECRET_KEY = os.getenv("SECRET_KEY")',
    }

    const [finding] = mapIssuesToFindings([issueWithProseAndCode])

    expect(finding.replacement_code).not.toBe(finding.suggestion)
    expect(finding.replacement_code).toBe('SECRET_KEY = os.getenv("SECRET_KEY")')
  })

  it('leaves replacement_code undefined if backend does not provide it', () => {
    const issueNoCode: CodeIssue = {
      file_path: 'utils.py',
      line_number: 10,
      severity: 'LOW',
      category: 'Code Quality',
      title: 'Missing Docstring',
      description: 'Function missing docstring',
      suggestion: 'Add a docstring explaining the method signature',
    }

    const [finding] = mapIssuesToFindings([issueNoCode])

    expect(finding.replacement_code).toBeUndefined()
    expect(finding.suggestion).toBe('Add a docstring explaining the method signature')
  })
})
