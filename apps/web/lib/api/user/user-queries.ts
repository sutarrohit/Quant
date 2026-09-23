import { mutationOptions, queryOptions } from "@tanstack/react-query";
import { completeOnboarding, getOnboardingStatus, getWallets, syncWallets } from "./user-apis";

// Consumed by components via useQuery / useMutation.
export function onboardingStatusQueryOptions() {
  return queryOptions({
    queryKey: ["user", "onboarding-status"],
    queryFn: () => getOnboardingStatus(),
  });
}

export function completeOnboardingMutationOptions() {
  return mutationOptions({
    mutationKey: ["user", "complete-onboarding"],
    mutationFn: () => completeOnboarding(),
  });
}

export function walletsQueryOptions() {
  return queryOptions({
    queryKey: ["user", "wallets"],
    queryFn: () => getWallets(),
  });
}

export function syncWalletsMutationOptions() {
  return mutationOptions({
    mutationKey: ["user", "wallets", "sync"],
    mutationFn: () => syncWallets(),
  });
}
