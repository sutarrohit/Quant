import { request } from "@/utils/request";

// ---------------------------------------------------------------------------
// DEMO: Frontend API client functions for user-related endpoints.
// Each function maps to a server route defined in apps/server/src/routes/user/.
// The request utility prepends the API base URL and handles JSON serialization.
// ---------------------------------------------------------------------------

export interface OnboardingStatusResponse {
  completed: boolean;
}


// DEMO: Fetches the onboarding status for the authenticated user.
// Corresponds to GET /api/v1/user/onboarding-status on the server.
export async function getOnboardingStatus(): Promise<OnboardingStatusResponse> {
  return request("/user/onboarding-status", { method: "GET" });
}

// DEMO: Marks the current user's onboarding as complete.
// Corresponds to POST /api/v1/user/complete-onboarding on the server.
// Returns void since the server responds with 204 No Content.
export async function completeOnboarding(): Promise<void> {
  return request("/user/complete-onboarding", { method: "POST" });
}
