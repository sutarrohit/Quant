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

// A wallet as the API returns it. `walletClient` is Privy's own discriminator:
// 'privy' is the embedded wallet created at login, anything else is one the user
// connected.
export interface WalletResponse {
  address: string;
  chainType: string;
  walletClient: string;
  firstVerifiedAt: string | null;
}

export interface WalletListResponse {
  wallets: WalletResponse[];
}

// Wallets already stored for the authenticated user.
// Corresponds to GET /api/v1/user/wallets on the server.
export async function getWallets(): Promise<WalletListResponse> {
  return request("/user/wallets", { method: "GET" });
}

// Asks the server to re-read this user's wallets from Privy and store them.
// Corresponds to POST /api/v1/user/wallets/sync.
//
// No body: the browser is what knows a wallet has appeared, but never what its
// address is as far as the server is concerned -- the server asks Privy.
export async function syncWallets(): Promise<WalletListResponse> {
  return request("/user/wallets/sync", { method: "POST" });
}
