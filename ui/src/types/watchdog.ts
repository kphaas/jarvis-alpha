export interface WatchdogEvent {
  id: string;
  service_name: string;
  node: string;
  event_type: string;
  previous_state: string | null;
  current_state: string | null;
  consecutive_failures: number;
  latency_ms: number | null;
  http_status: number | null;
  error_message: string | null;
  action_taken: string | null;
  created_at: string;
}

export interface WatchdogEventsResponse {
  events: WatchdogEvent[];
  total: number;
}

export interface WatchdogServiceStatus {
  service_name: string;
  node: string;
  current_state: string;
  last_event_at: string;
  consecutive_failures: number;
}

export interface WatchdogStatusResponse {
  services: WatchdogServiceStatus[];
  checked_at: string;
}
