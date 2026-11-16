"""Market prices (poe.ninja)."""
from soe.prices.ninja import Prices, default_prices


def safe_price(name: str | None) -> dict | None:
    """Compact price for display ({'divine', 'text'}), or None if unknown or poe.ninja is unreachable."""
    if not name:
        return None
    try:
        p = default_prices().price(name)
    except Exception:
        return None
    return {"divine": p["divine"], "text": p["text"]} if p else None


__all__ = ["Prices", "default_prices", "safe_price"]
