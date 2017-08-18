# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import sale
from . import wbs


def register():
    Pool.register(
        wbs.WorkBreakdownStructure,
        sale.Sale,
        sale.SaleLine,
        module='sale_wbs', type_='model')
