import type { LinkedAccount } from '@privy-io/node/resources';

// The token carries only the DID, so email and name live on the linked accounts
// and are fetched separately (see requireAuth). A wallet-only login has neither.
// Avatars use three different field names across providers, so all three are read.

const str = (value: unknown): string | null => (typeof value === 'string' && value.length > 0 ? value : null);

/**
 * Reduce linked accounts to the fields the local `user` row keeps.
 * Null is not an error -- a wallet-only login carries neither, hence the nullable columns.
 */
export function profileFromLinkedAccounts(accounts: readonly LinkedAccount[]): {
  email: string | null;
  name: string | null;
  image: string | null;
} {
  let email: string | null = null;
  let name: string | null = null;
  let image: string | null = null;

  for (const account of accounts) {
    if (account.type === 'email') {
      email ??= str(account.address); // Only here: a wallet's `address` is not an email.
      continue;
    }

    // `in` narrows across the union, so a provider Privy adds later works for free.
    if ('email' in account) email ??= str(account.email);
    if ('name' in account) name ??= str(account.name);

    if ('profile_picture_url' in account) image ??= str(account.profile_picture_url);
    if ('profile_picture' in account) image ??= str(account.profile_picture);
    if ('photo_url' in account) image ??= str(account.photo_url);
  }

  return { email, name, image };
}
