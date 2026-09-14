"use client";

import { useEffect, useState } from "react";

interface HealthStatus {
  status: "loading" | "ok" | "error";
  model?: string;
  error?: string;
}

export default function HealthCheck() {
  const [health, setHealth] = useState<HealthStatus>({ status: "loading" });

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const response = await fetch("/api/v1/health", {
          method: "GET",
          headers: { "Content-Type": "application/json" },
        });

        if (!response.ok) {
          throw new Error(`Health check failed: ${response.status}`);
        }

        const data = await response.json();
        setHealth({
          status: "ok",
          model: data.model,
        });
      } catch (err) {
        setHealth({
          status: "error",
          error: err instanceof Error ? err.message : "Unknown error",
        });
      }
    };

    checkHealth();
    const interval = setInterval(checkHealth, 30000); // Check every 30s
    return () => clearInterval(interval);
  }, []);

  if (health.status === "loading") {
    return (
      <div className="flex items-center gap-2 text-sm text-neutral-500">
        <div className="animate-spin rounded-full h-4 w-4 border border-neutral-300 border-t-neutral-600" />
        Checking backend...
      </div>
    );
  }

  if (health.status === "error") {
    return (
      <div className="flex items-center gap-2 text-sm text-red-600">
        <span className="text-lg">✗</span>
        Backend unavailable
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 text-sm text-green-600">
      <span className="text-lg">✓</span>
      Backend ready ({health.model})
    </div>
  );
}
