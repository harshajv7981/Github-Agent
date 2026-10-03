export type Repo = {
  name: string
  owner: string
  description: string
  stars: string
  language: string
  issues: number
  score: number
  trend: string
  color: string
  initials: string
}

export type SandboxReport = {
  success: boolean
  overall_status: 'passed' | 'warnings' | 'failed'
  score: number
  execution_time_seconds: number
  environment: string
  checks: {
    syntax: { passed: boolean; checked_files: string[]; errors: { file: string; message: string }[]; summary: string }
    linter: { passed: boolean; tool: string; warnings_count: number; warnings: { file: string; line: string; col: string; message: string }[]; summary: string }
    type_check: { passed: boolean; tool: string; errors_count: number; errors: string[]; summary: string }
    tests: { passed: boolean; tests_run: number; passed_count: number; failed_count: number; error_count: number; duration_seconds: number; output: string; summary: string }
  }
  summary: string
  modified_files: string[]
  file_rewrites?: Record<string, string>
  healing_analysis?: string
  healed?: boolean
  healing_attempts?: number
  healing_history?: { attempt: number; analysis: string; result_summary: string; passed: boolean }[]
}

export type RegressionTestResult = {
  issue_id: number
  test_path: string
  test_content: string
  explanation: string
  before_result: SandboxReport
  fails_before_patch: boolean
}

export type Issue = {
  id: number
  repo: string
  title: string
  number: string
  rawNumber: number
  label: string
  age: string
  difficulty: 'Good first issue' | 'Intermediate'
  body?: string
  ai_analysis?: string
  agent_status?: string
  sandbox_result?: SandboxReport
}

export type PullRequest = {
  id: number
  repository: string
  title: string
  number?: number
  url?: string
  status: string
  issue_number?: number
  issue_url?: string
  ai_summary?: string
  sandbox_result?: SandboxReport
  created_at: string
}

export type OllamaHealth = {
  ollama_connected: boolean
  configured_model: string
  model_available: boolean
  provider?: string
}

export type ActiveRun = {
  id: number
  name: string
  status: string
  repositories_scanned: number
  issues_found: number
  summary?: string
  created_at: string
}

export type AgentRun = {
  id: number
  issue_id?: number
  issue_title?: string
  issue_number?: number
  repository?: string
  status: string
  current_step: string
  attempt: number
  model_requests: number
  estimated_tokens: number
  failure_reason?: string
  created_at?: string
  updated_at?: string
}

export type AgentStep = {
  id: number
  step_key: string
  status: string
  attempt: number
  input: Record<string, unknown>
  output: Record<string, unknown>
  error?: string
}

export type FeatureSuggestion = {
  id: number
  repository: string
  title: string
  description: string
  category: string
  complexity: string
  impact_score: number
  implementation_plan: string
  suggested_files: string[]
  status: string
  ai_analysis?: string
  pr_title?: string
  pr_body?: string
  sandbox_result?: SandboxReport
  created_at: string
}

export type ImplementFeatureResult = {
  feature_id: number
  analysis: string
  pr_title: string
  pr_body: string
  acceptance_criteria?: string[]
  is_actionable?: boolean
  relevant_files: string[]
  file_rewrites: Record<string, string>
}
