"""Static XY stability metrics. Group by ID before using these functions."""
import math
import statistics


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    p = (len(values) - 1) * fraction
    low = int(p)
    return values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (p - low)


def describe(values):
    if not values:
        return {'count': 0}
    return {'count': len(values), 'min': min(values), 'max': max(values),
            'mean': statistics.mean(values), 'std': statistics.pstdev(values),
            'p95': percentile(values, .95)}


def analyze_xy(rows, step_threshold_m=.3, max_gap_sec=.5):
    rows = [r for r in rows if all(math.isfinite(r[k]) for k in ('t', 'x', 'y'))]
    if not rows:
        return {'count': 0}
    center = (statistics.median(r['x'] for r in rows), statistics.median(r['y'] for r in rows))
    radii = [math.dist((r['x'], r['y']), center) for r in rows]
    pairs = [(a, b) for a, b in zip(rows, rows[1:]) if b['t'] > a['t']]
    steps = [math.dist((a['x'], a['y']), (b['x'], b['y'])) for a, b in pairs]
    gaps = [b['t'] - a['t'] for a, b in pairs]
    connected_steps = [s for s, gap in zip(steps, gaps) if gap <= max_gap_sec]
    first = [r for r in rows if r['t'] <= rows[0]['t'] + 5]
    last = [r for r in rows if r['t'] >= rows[-1]['t'] - 5]
    mean_xy = lambda seq: (statistics.mean(r['x'] for r in seq), statistics.mean(r['y'] for r in seq))
    return {'count': len(rows), 'center_xy_m': list(center), 'radius_about_median_m': describe(radii),
            'adjacent_step_m': describe(steps), 'connected_step_m': describe(connected_steps),
            'step_threshold_m': step_threshold_m,
            'connected_jumps_over_threshold': sum(s > step_threshold_m for s in connected_steps),
            'gap_sec': describe(gaps), 'gaps_over_limit': sum(g > max_gap_sec for g in gaps),
            'non_increasing_receive_time': len(rows) - 1 - len(pairs),
            'first_to_last_5sec_mean_drift_m': math.dist(mean_xy(first), mean_xy(last))}
