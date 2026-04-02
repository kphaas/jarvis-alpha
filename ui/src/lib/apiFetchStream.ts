const BRAIN = import.meta.env.VITE_BRAIN_URL ?? "https://jarvis-brain.tail40ed36.ts.net:8186";

export interface StreamChunk {
  delta: string;
  model: string;
  thread_id: string;
  done: boolean;
  council_model?: string;
  council_detail?: Record<string, string>;
}

export async function apiFetchStream(
  path: string,
  body: object,
  onChunk: (chunk: StreamChunk) => void,
  onDone: (threadId: string, model: string, councilDetail?: Record<string, string>) => void,
  onError: (err: string) => void
): Promise<void> {
  const token = localStorage.getItem("alpha_token") ?? "";
  let response: Response;
  try {
    response = await fetch(`${BRAIN}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    });
  } catch (e) {
    onError(String(e));
    return;
  }

  if (!response.ok) {
    onError(`HTTP ${response.status}`);
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) { onError("No response body"); return; }

  const decoder = new TextDecoder();
  let buffer = "";
  let lastThreadId = "";
  let lastModel = "";
  let lastCouncilDetail: Record<string, string> | undefined;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      const raw = trimmed.slice(5).trim();
      if (raw === "[DONE]") {
        onDone(lastThreadId, lastModel, lastCouncilDetail);
        return;
      }
      try {
        const chunk: StreamChunk = JSON.parse(raw);
        if (chunk.thread_id) lastThreadId = chunk.thread_id;
        if (chunk.model) lastModel = chunk.model;
        if (chunk.council_detail) lastCouncilDetail = chunk.council_detail;
        if (!chunk.done) onChunk(chunk);
      } catch {
        // malformed line — skip
      }
    }
  }
  onDone(lastThreadId, lastModel, lastCouncilDetail);
}
