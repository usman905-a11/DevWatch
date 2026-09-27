export type IssueSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO';

export interface CodeIssue {
  finding_id?: string;
  file_path: string;
  line_number?: number;
  start_line?: number;
  end_line?: number;
  severity: IssueSeverity;
  category: string;
  title: string;
  description: string;
  suggestion: string;
  replacement_code?: string;
  verification_status?: string;
  cwe_id?: string;
  confidence_score?: number;
  code_snippet?: string;
  evidence?: Array<Record<string, unknown>>;
  specialist?: string;
  verification_confidence?: number;
  reproduction?: string;
}

export interface ReviewReport {
  target_path: string;
  issues: CodeIssue[];
  summary: string;
  total_issues: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  files_to_review?: string[];
  manual_review_candidates?: CodeIssue[];
  metrics?: Record<string, unknown>;
}

export interface AgentStepUpdate {
  agent_name: string;
  status: 'IDLE' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  message: string;
  timestamp?: number;
  elapsed_ms?: number;
  specialist?: string;
  tool_results?: Array<Record<string, unknown>>;
  token_usage?: Record<string, number>;
  suppressed_finding_count?: number;
}

export interface ReviewResponse {
  report_id: string;
  target_path: string;
  status: string;
  report: ReviewReport;
  summary_markdown: string;
  steps: AgentStepUpdate[];
}
