import { z } from '@hono/zod-openapi';

export const OnboardingStatusSchema = z.object({ completed: z.boolean() });

/** The wallet as the API hands it out -- not the row; `id` and `userId` are internal. */
export const WalletSchema = z.object({
  address: z.string(),
  chainType: z.string(),
  walletClient: z.string(), // Privy's discriminator: 'privy' is the wallet created at login.
  firstVerifiedAt: z.iso.datetime().nullable(),
});

export const WalletListSchema = z.object({ wallets: z.array(WalletSchema) });

export type OnboardingStatus = z.infer<typeof OnboardingStatusSchema>;
export type Wallet = z.infer<typeof WalletSchema>;
export type WalletList = z.infer<typeof WalletListSchema>;
