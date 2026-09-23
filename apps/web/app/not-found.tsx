import Link from 'next/link';

import { buttonVariants } from '@/components/ui/button';

export default function NotFound() {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 px-4 text-center">
      <p className="text-sm text-muted-foreground">404</p>
      <h1 className="text-xl font-semibold">No page here</h1>
      <p className="max-w-sm text-sm text-muted-foreground">The link may be old, or the page may have moved.</p>
      <Link href="/strategies" className={buttonVariants()}>
        Go to strategies
      </Link>
    </div>
  );
}
