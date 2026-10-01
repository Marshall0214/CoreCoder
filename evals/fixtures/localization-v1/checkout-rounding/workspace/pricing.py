from decimal import Decimal, ROUND_HALF_UP


def line_minor(price, quantity):
    amount = Decimal(str(price)) * quantity * 100
    return int(amount)
