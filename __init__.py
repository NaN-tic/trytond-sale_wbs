# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from .sale import *
from .wbs import *


def register():
    Pool.register(
        WorkBreakdownStructure,
        Sale,
        SaleLine,
        module='sale_wbs', type_='model')
