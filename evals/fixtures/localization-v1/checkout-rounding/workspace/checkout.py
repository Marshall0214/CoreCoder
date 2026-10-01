from fees import discount_minor
from pricing import line_minor


def submit_order(lines, discount_bps=0):
    subtotal = sum(line_minor(price, quantity) for price, quantity in lines)
    discount = discount_minor(subtotal, discount_bps)
    return {"subtotal_minor": subtotal, "discount_minor": discount,
            "payable_minor": subtotal - discount}
