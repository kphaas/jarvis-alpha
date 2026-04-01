const BASE = "/api"

export async function ask(payload: {
  prompt: string
  mode: string
  session_id: string
  user_id: string
  workspace_id?: string
  persistent?: boolean
}) {
  const res = await fetch(`${BASE}/v1/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  return res.json()
}

export async function getHealth() {
  const res = await fetch(`${BASE}/health`)
  return res.json()
}

export async function getPipeline() {
  const res = await fetch(`${BASE}/v1/vault/pipeline`)
  return res.json()
}
