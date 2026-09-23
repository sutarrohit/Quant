'use client';

// Replaces the root layout when it throws, so it brings its own <html> and no app styles can be assumed.
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: 'system-ui, sans-serif', display: 'grid', placeItems: 'center', minHeight: '100vh' }}>
        <div style={{ textAlign: 'center', maxWidth: 420, padding: 16 }}>
          <h1 style={{ fontSize: 20 }}>The app failed to load</h1>
          <p style={{ color: '#666', fontSize: 14 }}>{error.message || 'Something went wrong.'}</p>
          {error.digest && <p style={{ color: '#666', fontSize: 12 }}>Ref: {error.digest}</p>}
          <button onClick={reset} style={{ marginTop: 12, padding: '8px 16px', cursor: 'pointer' }}>
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
