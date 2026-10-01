from decimal import Decimal, ROUND_HALF_UP


def discount_minor(subtotal_minor, basis_points):
    amount = Decimal(subtotal_minor) * Decimal(basis_points) / 10000
    return int(amount)
