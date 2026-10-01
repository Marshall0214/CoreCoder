# Settlement contract

submit_order takes (decimal price, integer quantity) lines and integer discount basis points.
Convert each complete line to minor currency units with ROUND_HALF_UP.
Sum the rounded lines, then compute and ROUND_HALF_UP the discount in minor units.
payable_minor is subtotal_minor minus discount_minor. Never round unit price before multiplying quantity.
Legacy analytical reports intentionally use ROUND_HALF_EVEN. That separate behavior must remain.
