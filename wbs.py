# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from sql.aggregate import Sum

from trytond.model import ModelSQL, ModelView, fields
from trytond.pool import PoolMeta, Pool
from trytond.pyson import Eval, Bool, If
from trytond.transaction import Transaction
from trytond.tools import grouped_slice, reduce_ids

__all__ = ['WorkBreakdownStructure']
__metaclass__ = PoolMeta


class ChapterMixin:
    chapter_number = fields.Function(fields.Char('Chapter Number'),
        'get_chapter_number')

    @classmethod
    def get_1st_level_chapters(cls, records):
        """Return iterator over list of first records' ancestors children"""
        raise NotImplementedError

    @classmethod
    def get_chapter_number(cls, records, name):
        result = dict.fromkeys((r.id for r in records), None)
        # Calculate full sale to get the order correctly
        for children in cls.get_1st_level_chapters(records):
            values = cls._compute_chapter_number(children)
            for child_id, value in values.iteritems():
                if child_id not in result:
                    continue
                result[child_id] = value
        return result

    @classmethod
    def _compute_chapter_number(cls, children, prefix=None):
        if prefix is None:
            prefix = ''
        result = {}
        for i, child in enumerate(children, 1):
            result[child.id] = '%s%s' % (prefix, i)
            if child.childs:
                result.update(cls._compute_chapter_number(
                        child.childs, prefix=result[child.id] + '.'))
        return result


class WorkBreakdownStructure(ModelSQL, ModelView, ChapterMixin):
    'Work Breakdown Structure'
    __name__ = 'work.breakdown.structure'
    _rec_name = 'description'
    sequence = fields.Integer('Sequence')
    parent = fields.Many2One('work.breakdown.structure', 'Parent', select=True,
        left="left", right="right", ondelete="CASCADE")
    left = fields.Integer('Left', required=True, select=True)
    right = fields.Integer('Right', required=True, select=True)
    childs = fields.One2Many('work.breakdown.structure', 'parent', 'Children')
    type = fields.Selection('get_types', 'Type', required=True, select=True)
    description = fields.Char('Description', required=True)
    product = fields.Many2One('product.product', 'Product',
        domain=[('salable', '=', True)],
        states={
            'invisible': Eval('type') != 'line',
            },
        depends=['type'])
    product_uom_category = fields.Function(
        fields.Many2One('product.uom.category', 'Product Uom Category'),
        'on_change_with_product_uom_category')
    unit = fields.Many2One('product.uom', 'Unit',
            states={
                'required': Bool(Eval('product')),
                'invisible': Eval('type') != 'line',
            },
        domain=[
            If(Bool(Eval('product_uom_category')),
                ('category', '=', Eval('product_uom_category')),
                ('category', '!=', -1)),
            ],
        depends=['product', 'type', 'product_uom_category'])
    unit_digits = fields.Function(fields.Integer('Unit Digits'),
        'on_change_with_unit_digits')
    quantity = fields.Function(fields.Float('Quantity',
            digits=(16, Eval('unit_digits', 2)),
            states={
                'invisible': Eval('type') != 'line',
                },
            depends=['type', 'unit_digits']),
        'get_quantity')
    sale_lines = fields.One2Many('sale.line', 'wbs', 'Lines', readonly=True,
        domain=[
            ('type', '=', Eval('type')),
            ('product', '=', Eval('product')),
            ('unit', '=', Eval('unit')),
            ],
        depends=['type', 'product', 'unit'])
    sales = fields.Function(fields.One2Many('sale.sale', None, 'Sales'),
        'get_sales', searcher='search_sales')

    @classmethod
    def __setup__(cls):
        super(WorkBreakdownStructure, cls).__setup__()
        cls._order = [('sequence', 'ASC')]

    @staticmethod
    def order_sequence(tables):
        table, _ = tables[None]
        return [table.sequence == None, table.sequence]

    @staticmethod
    def default_left():
        return 0

    @staticmethod
    def default_right():
        return 0

    @staticmethod
    def get_types():
        pool = Pool()
        SaleLine = pool.get('sale.line')
        return SaleLine.type.selection

    @staticmethod
    def default_type():
        return 'line'

    @fields.depends('product')
    def on_change_with_product_uom_category(self, name=None):
        if self.product:
            return self.product.default_uom_category.id

    @staticmethod
    def default_unit_digits():
        return 2

    @fields.depends('unit')
    def on_change_with_unit_digits(self, name=None):
        if self.unit:
            return self.unit.digits
        return 2

    @classmethod
    def get_quantity(cls, wbs, name):
        pool = Pool()
        line = pool.get('sale.line').__table__()
        cursor = Transaction().cursor

        wbs_ids = [w.id for w in wbs]
        result = {}.fromkeys(wbs_ids, 0.0)

        query = line.select(line.wbs, Sum(line.quantity),
            group_by=line.wbs)
        for sub_ids in grouped_slice(wbs_ids):
            query.where = reduce_ids(line.wbs, sub_ids)
            cursor.execute(*query)
            result.update(dict(cursor.fetchall()))
        return result

    def get_sales(self, name):
        return list({l.sale.id for l in self.sale_lines})

    @classmethod
    def search_sales(cls, name, clause):
        return [tuple(('sale_lines.sale',)) + tuple(clause[1:])]

    @classmethod
    def get_1st_level_chapters(cls, records):
        for sale in {s for r in records for s in r.sales}:
            yield sale.wbs_tree
