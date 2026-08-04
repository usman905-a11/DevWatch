import { ReviewResponse, AgentStepUpdate } from '../types';

const API_BASE_URL = 'http://localhost:8000/api';
const WS_BASE_URL = 'ws://localhost:8000/ws/review';

export async function runCodeReview(targetPath: string): Promise<ReviewResponse> {
  const response = await fetch(`${API_BASE_URL}/review`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ target_path: targetPath }),
  });

  if (!response.ok) {
    const errorData = await response.json();
    throw new Error(errorData.detail || 'Failed to start code review');
  }

  return response.json();
}

export async function fetchFileTree(rootPath: string = '.'): Promise<{ root: string; tree: any[]; files: string[] }> {
  const response = await fetch(`${API_BASE_URL}/fs/tree?root=${encodeURIComponent(rootPath)}`);
  if (!response.ok) {
    throw new Error('Failed to fetch filesystem tree');
  }
  return response.json();
}

export async function fetchFileContent(filePath: string, rootPath: string = '.'): Promise<{ path: string; content: string }> {
  const response = await fetch(
    `${API_BASE_URL}/fs/read?path=${encodeURIComponent(filePath)}&root=${encodeURIComponent(rootPath)}`
  );
  if (!response.ok) {
    throw new Error(`Failed to read file: ${filePath}`);
  }
  return response.json();
}

export async function saveFileContent(filePath: string, content: string, rootPath: string = '.'): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/fs/write`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ root_path: rootPath, file_path: filePath, content }),
  });
  if (!response.ok) {
    throw new Error(`Failed to save file: ${filePath}`);
  }
  return response.json();
}

export async function auditSingleFile(filePath: string, content: string): Promise<ReviewResponse> {
  const response = await fetch(`${API_BASE_URL}/review/file`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file_path: filePath, content }),
  });
  if (!response.ok) {
    throw new Error(`Failed to audit file: ${filePath}`);
  }
  return response.json();
}

export async function runUploadedFilesReview(files: Array<{ file_path: string; content: string }>): Promise<ReviewResponse> {
  const response = await fetch(`${API_BASE_URL}/review/files`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ files }),
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Failed to run files review' }));
    throw new Error(errorData.detail || 'Failed to start uploaded files review');
  }
  return response.json();
}

export function subscribeToReviewStream(
  targetPath: string,
  onStep: (step: AgentStepUpdate) => void,
  onComplete: (reportData: any) => void,
  onError: (err: any) => void
): () => void {
  const ws = new WebSocket(WS_BASE_URL);

  ws.onopen = () => {
    ws.send(JSON.stringify({ target_path: targetPath }));
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.status === 'COMPLETED') {
        onComplete(data);
      } else {
        onStep(data);
      }
    } catch (e) {
      onError(e);
    }
  };

  ws.onerror = (error) => {
    onError(error);
  };

  return () => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.close();
    }
  };
}

export async function applyQuickFix(
  filePath: string,
  lineNumber: number = 1,
  targetSnippet: string = '',
  replacementCode: string = '',
  rootPath: string = '.'
): Promise<{ status: string; file_path: string; line_number: number; modified: boolean }> {
  const response = await fetch(`${API_BASE_URL}/review/apply-fix`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      root_path: rootPath,
      file_path: filePath,
      line_number: lineNumber,
      target_snippet: targetSnippet,
      replacement_code: replacementCode,
    }),
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Quick fix failed' }));
    throw new Error(errorData.detail || 'Failed to apply quick fix');
  }
  return response.json();
}


