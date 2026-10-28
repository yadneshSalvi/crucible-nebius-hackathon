import { createContext, useContext } from "react";
import type { Health } from "./types";

export interface ProviderStatus {
  label: string;
  nebiusQualification: string;
}

const unavailable: ProviderStatus = {
  label: "the configured NVIDIA provider",
  nebiusQualification: "not reported",
};

export const ProviderContext = createContext<ProviderStatus>(unavailable);
export const useProviderStatus = () => useContext(ProviderContext);

export function providerStatus(health: Health | null): ProviderStatus {
  if (!health?.provider || typeof health.provider !== "object")
    return unavailable;
  const config = health.provider as Record<string, unknown>;
  const provider = typeof config.provider === "string" ? config.provider : "";
  const model = typeof config.model === "string" ? config.model : "";
  const name =
    provider === "fireworks"
      ? "Fireworks"
      : provider === "nebius"
        ? "Nebius"
        : provider;
  const nebius =
    config.nebius && typeof config.nebius === "object"
      ? (config.nebius as Record<string, unknown>)
      : null;
  return {
    label: name
      ? `${name}${/nemotron/i.test(model) ? " · NVIDIA Nemotron" : model ? ` · ${model}` : ""}`
      : unavailable.label,
    nebiusQualification:
      typeof nebius?.qualification === "string"
        ? nebius.qualification
        : unavailable.nebiusQualification,
  };
}
