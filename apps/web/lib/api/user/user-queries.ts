import { mutationOptions, queryOptions } from "@tanstack/react-query";
import { completeOnboarding, getOnboardingStatus } from "./user-apis";

// ---------------------------------------------------------------------------
// DEMO: TanStack React Query options for user-related operations.
// These are consumed by React components via useMutation / useQuery.
//
// Usage example in a component:
//   const { mutate } = useMutation(completeOnboardingMutationOptions());
//   mutate(); // triggers POST /api/v1/user/complete-onboarding
// ---------------------------------------------------------------------------

// Query options for fetching onboarding status.
export function onboardingStatusQueryOptions() {
  return queryOptions({
    queryKey: ["user", "onboarding-status"],
    queryFn: () => getOnboardingStatus(),
  });
}

// Mutation options for completing onboarding.
export function completeOnboardingMutationOptions() {
  return mutationOptions({
    mutationKey: ["user", "complete-onboarding"],
    mutationFn: () => completeOnboarding(),
  });
}
