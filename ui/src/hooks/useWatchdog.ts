import { useQuery } from "@tanstack/react-query";
import { apiJson } from "../lib/apiFetch";
import type {
  WatchdogEventsResponse,
  WatchdogStatusResponse,
} from "../types/watchdog";

export function useWatchdogEvents(limit = 10) {
  return useQuery({
    queryKey: ["watchdog", "events", limit],
    queryFn: () =>
      apiJson<WatchdogEventsResponse>(`/v1/watchdog/events?limit=${limit}`),
    staleTime: 25_000,
    refetchInterval: 30_000,
  });
}

export function useWatchdogStatus() {
  return useQuery({
    queryKey: ["watchdog", "status"],
    queryFn: () => apiJson<WatchdogStatusResponse>("/v1/watchdog/status"),
    staleTime: 25_000,
    refetchInterval: 30_000,
  });
}
