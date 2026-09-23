import { request } from "@/utils/request";

// One function per route in apps/server/src/routes/user/.
export interface OnboardingStatusResponse {
  completed: boolean;
}


// GET /api/v1/user/onboarding-status
export async function getOnboardingStatus(): Promise<OnboardingStatusResponse> {
  return request("/user/onboarding-status", { method: "GET" });
}

// POST /api/v1/user/complete-onboarding. Void: the server answers 204.
export async function completeOnboarding(): Promise<void> {
  return request("/user/complete-onboarding", { method: "POST" });
}

// `walletClient` is Privy's discriminator: 'privy' is the wallet created at login.
export interface WalletResponse {
  address: string;
  chainType: string;
  walletClient: string;
  firstVerifiedAt: string | null;
}

export interface WalletListResponse {
  wallets: WalletResponse[];
}

// GET /api/v1/user/wallets
export async function getWallets(): Promise<WalletListResponse> {
  return request("/user/wallets", { method: "GET" });
}

// POST /api/v1/user/wallets/sync. No body: the browser knows a wallet appeared,
// never what its address is -- the server asks Privy.
export async function syncWallets(): Promise<WalletListResponse> {
  return request("/user/wallets/sync", { method: "POST" });
}
