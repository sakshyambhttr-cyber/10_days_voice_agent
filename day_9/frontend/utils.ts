import { cache } from "react";
import { TokenSource } from "livekit-client";
import { APP_CONFIG_DEFAULTS } from "@/app-config";
import type { AppConfig } from "@/app-config";

export const CONFIG_ENDPOINT = process.env.NEXT_PUBLIC_APP_CONFIG_ENDPOINT;
export const SANDBOX_ID = process.env.SANDBOX_ID;

export interface SandboxConfig {
  [key: string]:
    | { type: "string"; value: string }
    | { type: "number"; value: number }
    | { type: "boolean"; value: boolean }
    | null;
}

/**
 * Get the app configuration
 * @param headers - The headers of the request
 * @returns The app configuration
 *
 * @note React will invalidate the cache for all memoized functions for each server request.
 * https://react.dev/reference/react/cache#caveats
 */
export const getAppConfig = cache(
  async (headers: Headers): Promise<AppConfig> => {
    if (CONFIG_ENDPOINT) {
      const sandboxId = SANDBOX_ID ?? headers.get("x-sandbox-id") ?? "";

      try {
        if (!sandboxId) {
          throw new Error("Sandbox ID is required");
        }

        const response = await fetch(CONFIG_ENDPOINT, {
          cache: "no-store",
          headers: { "X-Sandbox-ID": sandboxId },
        });

        if (response.ok) {
          const remoteConfig: SandboxConfig = await response.json();

          const config: AppConfig = { ...APP_CONFIG_DEFAULTS, sandboxId };

          for (const [key, entry] of Object.entries(remoteConfig)) {
            if (entry === null) continue;
            // Only include app config entries that are declared in defaults and, if set,
            // share the same primitive type as the default value.
            if (
              (key in APP_CONFIG_DEFAULTS &&
                APP_CONFIG_DEFAULTS[key as keyof AppConfig] === undefined) ||
              (typeof config[key as keyof AppConfig] === entry.type &&
                typeof config[key as keyof AppConfig] === typeof entry.value)
            ) {
              // @ts-expect-error I'm not sure quite how to appease TypeScript, but we've thoroughly checked types above
              config[key as keyof AppConfig] =
                entry.value as AppConfig[keyof AppConfig];
            }
          }

          return config;
        } else {
          console.error(
            `ERROR: querying config endpoint failed with status ${response.status}: ${response.statusText}`,
          );
        }
      } catch (error) {
        console.error("ERROR: getAppConfig() - lib/utils.ts", error);
      }
    }

    return APP_CONFIG_DEFAULTS;
  },
);

/**
 * Get styles for the app
 * @param appConfig - The app configuration
 * @returns A string of styles
 */
export function getStyles(appConfig: AppConfig) {
  const { accent, accentDark } = appConfig;

  return [
    accent
      ? `:root { --primary: ${accent}; --primary-hover: color-mix(in srgb, ${accent} 80%, #000); }`
      : "",
    accentDark
      ? `.dark { --primary: ${accentDark}; --primary-hover: color-mix(in srgb, ${accentDark} 80%, #000); }`
      : "",
  ]
    .filter(Boolean)
    .join("\n");
}

/**
 * Get a token source for a sandboxed LiveKit session
 * @param appConfig - The app configuration
 * @returns A token source for a sandboxed LiveKit session
 */
export function getSandboxTokenSource(appConfig: AppConfig) {
  return TokenSource.custom(async () => {
    const url = new URL(
      process.env.NEXT_PUBLIC_CONN_DETAILS_ENDPOINT!,
      window.location.origin,
    );
    const sandboxId = appConfig.sandboxId ?? "";
    const roomConfig = appConfig.agentName
      ? {
          agents: [{ agent_name: appConfig.agentName }],
        }
      : undefined;

    try {
      const res = await fetch(url.toString(), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Sandbox-Id": sandboxId,
        },
        body: JSON.stringify({
          room_config: roomConfig,
        }),
      });
      return await res.json();
    } catch (error) {
      console.error("Error fetching connection details:", error);
      throw new Error("Error fetching connection details!");
    }
  });
}

/**
 * Get or create persistent user ID stored in localStorage
 */
export function getPersistentUserId(): string {
  if (typeof window === "undefined") return "";
  try {
    let userId = localStorage.getItem("bolbuddy_user_id");
    if (!userId) {
      userId = `bolbuddy_user_${Math.random().toString(36).substring(2, 10)}${Date.now().toString(36)}`;
      localStorage.setItem("bolbuddy_user_id", userId);
    }
    return userId;
  } catch {
    return "";
  }
}

/**
 * Reset persistent user ID when user deletes memory
 */
export function resetPersistentUserId(): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem("bolbuddy_user_id");
  } catch {
    // Ignore storage errors
  }
}

/**
 * Sanitize chat message text to strip raw tool execution tags, XML, and function JSON payloads
 * while preserving all conversational dialogue.
 */
export function cleanChatMessage(text: string): string {
  if (!text) return "";
  let cleaned = String(text);

  // 1. Strip XML/HTML function tags e.g. <function=...> or </function> or <tool_call...>
  cleaned = cleaned.replace(
    /<\/?(?:function|tool_call|tool|action)[^>]*>/gi,
    "",
  );
  cleaned = cleaned.replace(/<[^>]+>/g, "");

  // 2. Strip function call syntax e.g. fetch_next_exercise>{"level": "beginner", ...}
  cleaned = cleaned.replace(/\b\w+>\{[^}]*\}/gi, "");
  cleaned = cleaned.replace(/\b\w+>\{[^\s]*/gi, "");

  // 3. Strip function invocation with parentheses e.g. transfer_to_interview_buddy(role='dev')
  cleaned = cleaned.replace(/\b\w+\([^)]*\)/gi, "");

  // 4. Strip raw tool names without wiping out following conversational text
  cleaned = cleaned.replace(
    /\b(?:transfer_to_interview_buddy|transfer_to_bolbuddy|fetch_next_exercise|score_spoken_answer|create_escalation|lookup_user_memory|save_user_memory|forget_my_data|what_do_you_remember|search_learning_resources|mark_call_outcome)\b(?:\([^)]*\)|>\s*\{[^}]*\}|>\s*[^\s]+)?/gi,
    "",
  );

  // 5. Strip standalone JSON objects e.g. {"score": 8, ...} or {"target_role": "..."}
  cleaned = cleaned.replace(/\{[^{}]*\}/g, "");

  // 6. Clean markdown symbols and extra whitespace
  cleaned = cleaned.replace(/[`*_~#]/g, "");
  return cleaned.replace(/\s+/g, " ").trim();
}
