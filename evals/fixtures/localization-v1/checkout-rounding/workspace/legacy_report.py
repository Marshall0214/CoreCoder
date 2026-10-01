from decimal import Decimal, ROUND_HALF_EVEN


def report_minor(price):
    return int((Decimal(str(price)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))
