import type { LinkedAccount } from '@privy-io/node/resources';

// Privy's access token carries only the user's DID -- no email, no name. Profile
// fields live on the user's *linked accounts*, which have to be fetched
// separately (see requireAuth).
//
// Shapes, verified against @privy-io/node's published types:
//   { type: 'email',        address: string }
//   { type: 'google_oauth', email: string, name: string | null }
//   { type: 'wallet',       address: string }            <- no email or name
// Other OAuth providers follow the google_oauth shape, though some (apple_oauth)
// have a nullable email and carry no name at all.
//
// Avatars are messier: Google supplies none, and the providers that do use three
// different field names -- `profile_picture_url` (twitter, line, custom oauth),
// `profile_picture` (farcaster) and `photo_url` (telegram). All three are read.

const str = (value: unknown): string | null =>
  typeof value === 'string' && value.length > 0 ? value : null;

/**
 * Reduce a Privy user's linked accounts to the fields the local `user` row keeps.
 *
 * Both may legitimately come back null: a wallet-only login carries neither, which
 * is precisely why both columns are nullable. Null here is not an error.
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
      // Only read `address` under this branch. Wallet accounts also have an
      // `address`, and it is a wallet address, not an email.
      email ??= str(account.address);
      continue;
    }

    // `in` narrows across the union, so every provider is handled without
    // enumerating them -- and a provider Privy adds later works for free.
    if ('email' in account) email ??= str(account.email);
    if ('name' in account) name ??= str(account.name);

    if ('profile_picture_url' in account) image ??= str(account.profile_picture_url);
    if ('profile_picture' in account) image ??= str(account.profile_picture);
    if ('photo_url' in account) image ??= str(account.photo_url);
  }

  return { email, name, image };
}
