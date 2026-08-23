import { useQuery } from "@tanstack/react-query";

import { useLiveUpdates } from "@/hooks/use-live-updates";
import { livePoll } from "@/lib/query";
import { fetchPaperV2 } from "@/lib/paper-v2";

const V2_POLL_MS = 15_000;

export function usePaperV2() {
  const { status } = useLiveUpdates();
  return useQuery({
    queryKey: ["paper-v2", "wallet"],
    queryFn: fetchPaperV2,
    refetchInterval: livePoll(status, V2_POLL_MS),
    staleTime: V2_POLL_MS / 2,
  });
}
