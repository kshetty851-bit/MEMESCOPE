"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        // Off for healthy queries — refetching everything each time the tab
        // regains focus is churn, and the live stream already pushes changes.
        //
        // On for broken ones. Several queries have no polling interval at all
        // (`usePaperStrategies`, `useRadarModel`, the token page's history),
        // so once they error there is nothing left to retry them and the
        // screen stays broken for the life of the tab. Coming back to the tab
        // is the one moment a user is definitely asking to see it again.
        refetchOnWindowFocus: (query) => query.state.status === "error",
        retry: (failureCount, error) => {
          // Auth and client errors will not fix themselves on a retry.
          if (error instanceof ApiError && error.status < 500) return false;
          return failureCount < 2;
        },
      },
    },
  });
}

export function Providers({ children }: { children: React.ReactNode }) {
  // Created in state so a re-render never discards the cache.
  const [queryClient] = useState(makeQueryClient);
  const bootstrap = useAuthStore((state) => state.bootstrap);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  // The live-update socket is deliberately NOT mounted here.
  //
  // This provider wraps every route, including the public landing page, and
  // the token stream is refused without an alpha cookie — so mounting it at
  // the document root opened a socket for every anonymous visitor, had it
  // closed on policy grounds, and reconnected on a backoff for as long as the
  // tab stayed open. The stream belongs to the authenticated application, so
  // `LiveUpdatesProvider` now lives in the dashboard layout, behind the same
  // access check as the screens that consume it.
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
