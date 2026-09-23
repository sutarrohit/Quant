/** Local user row attached by requireAuth. Mirrors the Prisma `User` model. */
export interface AuthUser {
  id: string;
  privyDid: string;
  name: string | null; // Nullable: Privy identifies by DID, and a wallet-only login has no name.
  email: string | null; // Same, so never key domain data off it.
  image: string | null;
  onboardingCompletedAt: Date | null;
  createdAt: Date;
  updatedAt: Date;
}
