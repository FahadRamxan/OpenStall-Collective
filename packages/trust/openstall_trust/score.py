"""The seller trust score from spec 3.7: T = 0.4 on_time + 0.3 (1 - dispute) + 0.3 photo."""

from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")


def trust_score(
    on_time_rate: float | Decimal,
    dispute_rate: float | Decimal,
    photo_originality: float | Decimal,
) -> Decimal:
    """Score a seller from 0.00 to 1.00, rounded half-up to 2 places.

    Each input is a rate from 0 to 1. A rate outside that range, NaN or a non-number raises.
    """
    on_time = _rate("on_time_rate", on_time_rate)
    dispute = _rate("dispute_rate", dispute_rate)
    photo = _rate("photo_originality", photo_originality)
    score = Decimal("0.4") * on_time + Decimal("0.3") * (1 - dispute) + Decimal("0.3") * photo
    return score.quantize(_CENT, rounding=ROUND_HALF_UP)


def _rate(name: str, value: float | Decimal) -> Decimal:
    # bool is a subclass of int, but True passed as a rate is a bug, not 1.0.
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(f"{name} must be a number, not {type(value).__name__}")
    # Through str() so 0.95 counts as 0.95, not as its binary approximation 0.94999...
    rate = Decimal(str(value))
    if not rate.is_finite() or not 0 <= rate <= 1:
        raise ValueError(f"{name} must be between 0 and 1, got {value!r}")
    return rate
