from decimal import Decimal
from roya.common.money import format_minor,to_minor_units

def test_naira_to_minor_units():
    assert to_minor_units(Decimal("75000.00"))==7_500_000

def test_format_naira_minor_units():
    assert format_minor(7_500_000,"NGN")=="₦75,000.00"
