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
