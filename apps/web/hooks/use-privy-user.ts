"use client"

import { usePrivy } from "@privy-io/react-auth"

/**
 * The signed-in user, shaped for the sidebar footer.
 *
 * Privy identifies a user by DID, so a wallet-only login has neither a name nor
 * an email -- the wallet address stands in rather than leaving the row blank.
 */
export function usePrivyUser() {
  const { user } = usePrivy()

  const wallet = user?.wallet?.address
  const email = user?.email?.address ?? user?.google?.email ?? ""
  const short = wallet ? `${wallet.slice(0, 6)}…${wallet.slice(-4)}` : ""

  return {
    name: user?.google?.name ?? email.split("@")[0] ?? short ?? "Signed in",
    email: email || short,
    avatar: "",
  }
}
