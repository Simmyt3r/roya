from decimal import Decimal, ROUND_HALF_UP


def to_minor_units(amount: Decimal | str | int | float, exponent: int = 2) -> int:
    value = Decimal(str(amount))
    factor = Decimal(10) ** exponent
    return int((value * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_minor(amount_minor: int, currency: str = "NGN", exponent: int = 2) -> str:
    factor = 10**exponent
    value = amount_minor / factor
    symbol = "₦" if currency.upper() == "NGN" else f"{currency.upper()} "
    return f"{symbol}{value:,.2f}"
