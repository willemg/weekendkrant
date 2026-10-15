"""Pure reference adapter for the single hourly scheduled executor.

No scheduler or backend side effects. Capture the result once at entry and retain
it for every transport retry, even outside the admission window or next hour.
The cloud task implements this same contract; it does not import this module.
"""
from datetime import datetime, timedelta, timezone

SCHEDULER_ID = 'weekendkrant:executor-1'
SLOT_TOLERANCE = timedelta(minutes=15)


def start_arguments(now: datetime):
    """Return frozen start arguments, or None outside inclusive +/-15 minutes.

    Normalize to UTC before rounding to the nearest hour; half-hour ties round
    forward (and are outside tolerance). Use exact timedelta arithmetic.

    Caller must supply a fresh trustworthy timezone-aware clock observation.
    Naive/local assumptions are rejected. This is our logical slot, not a
    platform occurrence attestation or a clock-skew correction mechanism.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('A trustworthy timezone-aware clock is required')
    utc = now.astimezone(timezone.utc)
    slot = utc.replace(minute=0, second=0, microsecond=0)
    if utc - slot >= timedelta(minutes=30):
        slot += timedelta(hours=1)
    if abs(utc - slot) > SLOT_TOLERANCE:
        return None
    activation_id = SCHEDULER_ID + ':' + slot.strftime('%Y-%m-%dT%H:00:00Z')
    return dict(activation_id=activation_id, operation_id='start:' + activation_id)
