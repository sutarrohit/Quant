/**
 * Largest-Triangle-Three-Buckets: thin a series to `threshold` points while
 * keeping its peaks and troughs, which a plain stride would skip.
 *
 * `value` is read only to choose points; the points themselves are returned
 * untouched, so decimal strings stay strings.
 */
export function lttb<T>(points: T[], threshold: number, value: (point: T) => number): T[] {
  if (threshold >= points.length || threshold < 3) return points;

  const sampled: T[] = [points[0]!];
  const bucketSize = (points.length - 2) / (threshold - 2);
  let anchor = 0; // Index of the last point kept.

  for (let bucket = 0; bucket < threshold - 2; bucket++) {
    const start = Math.floor(bucket * bucketSize) + 1;
    const end = Math.floor((bucket + 1) * bucketSize) + 1;

    // The next bucket's average is the triangle's third corner.
    const nextEnd = Math.min(Math.floor((bucket + 2) * bucketSize) + 1, points.length);
    let avgX = 0;
    let avgY = 0;
    for (let i = end; i < nextEnd; i++) {
      avgX += i;
      avgY += value(points[i]!);
    }
    const count = Math.max(nextEnd - end, 1);
    avgX /= count;
    avgY /= count;

    const anchorY = value(points[anchor]!);
    let best = start;
    let bestArea = -1;
    for (let i = start; i < end; i++) {
      const area = Math.abs((anchor - avgX) * (value(points[i]!) - anchorY) - (anchor - i) * (avgY - anchorY));
      if (area > bestArea) {
        bestArea = area;
        best = i;
      }
    }

    sampled.push(points[best]!);
    anchor = best;
  }

  sampled.push(points[points.length - 1]!);
  return sampled;
}
