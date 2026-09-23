"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  RiFlaskLine,
  RiLineChartLine,
  RiPulseLine,
} from "@remixicon/react"

import { NavMain } from "@/components/nav-main"
import { NavUser } from "@/components/nav-user"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import { usePrivyUser } from "@/hooks/use-privy-user"

const NAV = [
  {
    title: "Strategies",
    url: "/strategies",
    icon: <RiLineChartLine />,
    items: [
      { title: "All strategies", url: "/strategies" },
      { title: "New strategy", url: "/strategies/new" },
    ],
  },
  {
    title: "Backtests",
    url: "/backtests",
    icon: <RiFlaskLine />,
    items: [{ title: "Runs", url: "/backtests" }],
  },
  {
    title: "Simulations",
    url: "/simulations",
    icon: <RiPulseLine />,
    items: [{ title: "Accounts", url: "/simulations" }],
  },
]

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const pathname = usePathname()
  const user = usePrivyUser()

  // A group opens when the current route is inside it, so a reload lands with
  // the right section already expanded.
  const items = NAV.map((item) => ({
    ...item,
    isActive: pathname.startsWith(item.url),
  }))

  return (
    <Sidebar variant="inset" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" render={<Link href="/dashboard" />}>
              <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                <RiLineChartLine className="size-4" />
              </div>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">Quant</span>
                <span className="truncate text-xs">Strategy platform</span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={items} />
      </SidebarContent>
      <SidebarFooter>
        <NavUser user={user} />
      </SidebarFooter>
    </Sidebar>
  )
}
