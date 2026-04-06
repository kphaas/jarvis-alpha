import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../lib/apiFetch";
import type { ErrorLogEntry as LogEntry, QueryResponse } from "../types/errors";

interface UseLogsParams {
  since: string;
  selectedNodes: Set<string>;
  selectedLevels: Set<string>;
  service: string;
  textSearch: string;
}

interface UseLogsResult {
  entries: LogEntry[];
  count: number;
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useLogs(params: UseLogsParams, autoRefresh: boolean): UseLogsResult {
  const query = useQuery({
    queryKey: [
      "logs",
      "query",
      params.since,
      Array.from(params.selectedNodes).sort().join(","),
      Array.from(params.selectedLevels).sort().join(","),
      params.service,
      params.textSearch.trim(),
    ],
    queryFn: async () => {
      const urlParams = new URLSearchParams();
      urlParams.set("nodes", Array.from(params.selectedNodes).join(","));
      urlParams.set("levels", Array.from(params.selectedLevels).join(","));
      if (params.service !== "all") {
        urlParams.set("service", params.service);
      }
      const search = params.textSearch.trim();
      if (search) {
        urlParams.set("search", search);
      }
      urlParams.set("limit", "500");
      urlParams.set("since", params.since);

      const res = await apiFetch(`/v1/logs/query?${urlParams.toString()}`);
      const data = (await res.json()) as QueryResponse;
      if (!res.ok || data.status === "error") {
        throw new Error(data.error || `HTTP ${res.status}`);
      }
      return {
        entries: data.entries ?? [],
        count: data.count ?? 0,
      };
    },
    staleTime: 30_000,
    refetchInterval: autoRefresh ? 30_000 : false,
  });

  return {
    entries: query.data?.entries ?? [],
    count: query.data?.count ?? 0,
    isLoading: query.isLoading,
    error: query.error ? String(query.error) : null,
    refetch: () => {
      void query.refetch();
    },
  };
}
