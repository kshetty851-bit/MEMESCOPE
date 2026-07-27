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
        refetchOnWindowFocus: false,
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

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
