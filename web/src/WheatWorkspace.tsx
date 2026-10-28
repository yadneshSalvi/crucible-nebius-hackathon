import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { Wheat } from "./Wheat";
import type { WheatStudy } from "./wheat-types";

export function WheatWorkspace({ onHistory }: { onHistory: () => void }) {
  const [study, setStudy] = useState<WheatStudy | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [version, setVersion] = useState(0);
  const mutation = useRef(false);
  const latest = useRef<WheatStudy | null>(null);
  const accept = useCallback((next: WheatStudy) => {
    if (latest.current && latest.current.revision > next.revision) return;
    latest.current = next;
    setStudy(next);
  }, []);

  useEffect(() => {
    document.title = "Crucible — Pixels, counted.";
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      let delay = 8000;
      try {
        const next = await api.wheat();
        if (!alive) return;
        accept(next);
        setError(null);
        if (
          next.run &&
          ["queued", "running", "cancel_requested"].includes(next.run.status)
        )
          delay = 1500;
      } catch (failure) {
        if (!alive) return;
        setError(
          failure instanceof Error
            ? failure.message
            : "The saved wheat study could not be read.",
        );
        delay = 5000;
      } finally {
        if (alive) {
          setLoading(false);
          timer = setTimeout(() => void poll(), delay);
        }
      }
    }
    void poll();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [accept, version]);

  async function action(name: string, payload: Record<string, unknown> = {}) {
    if (mutation.current || !latest.current) return;
    mutation.current = true;
    setPending(true);
    setError(null);
    try {
      accept(await api.wheatAction(latest.current, name, payload));
      setVersion((value) => value + 1);
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "The action failed. Saved evidence is retained.",
      );
      if (
        failure instanceof ApiError &&
        /revision|conflict|stale|session/.test(failure.code)
      ) {
        try {
          accept(await api.wheat());
        } catch {
          /* Preserve the last durable state. */
        }
      }
    } finally {
      mutation.current = false;
      setPending(false);
    }
  }

  return (
    <Wheat
      study={study}
      loading={loading}
      error={error}
      pending={pending}
      onAction={(name, payload) => void action(name, payload)}
      onHistory={onHistory}
      onRefresh={() => setVersion((value) => value + 1)}
    />
  );
}
