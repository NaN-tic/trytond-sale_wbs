# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from decimal import Decimal
from itertools import chain

from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.transaction import Transaction

from .wbs import ChapterMixin

__all__ = ['Sale', 'SaleLine']
__metaclass__ = PoolMeta


class Sale:
    __name__ = 'sale.sale'
    lines_tree = fields.Function(fields.One2Many('sale.line', 'sale', 'Lines',
            domain=[
                ('parent', '=', None),
                ]),
        'get_lines_tree', setter='set_lines_tree')
    wbs_tree = fields.Function(fields.One2Many('work.breakdown.structure',
            None, 'Work Breakdown Structure'),
        'get_wbs_tree')

    @classmethod
    def __setup__(cls):
        super(Sale, cls).__setup__()
        if cls.lines.domain:
            cls.lines_tree._field.domain.extend(cls.lines.domain)
        cls.lines_tree._field.states = cls.lines.states
        cls.lines_tree._field.depends = cls.lines.depends
        # Quote button should be updated as it depends on lines
        cls._buttons['quote']['readonly'] = ~Eval('lines_tree', [])

    def get_lines_tree(self, name):
        return [x.id for x in self.lines if not x.parent]

    @classmethod
    def set_lines_tree(cls, lines, name, value):
        cls.write(lines, {
                'lines': value,
                })

    @fields.depends('lines_tree', methods=['lines'])
    def on_change_lines_tree(self, name=None):
        self.lines = self.lines_tree
        return self.on_change_lines()

    def get_wbs_tree(self, name):
        pool = Pool()
        WBS = pool.get('work.breakdown.structure')

        def _get_parents(wbs):
            if wbs.parent == None:
                return wbs.id
            else:
                return _get_parents(wbs.parent)

        res = []
        for wbs in WBS.search([('sales', 'in', [self.id])]):
            wbs_parent = _get_parents(wbs)
            if wbs_parent and wbs_parent not in res:
                res.append(wbs_parent)
        return res

    def _get_invoice_line_sale_line(self, invoice_type):
        '''
        If any line is returned we must ensure that all the structure is
        created on the invoice. We do it by creating comment lines.
        '''
        pool = Pool()
        InvoiceLine = pool.get('account.invoice.line')
        res = super(Sale, self)._get_invoice_line_sale_line(invoice_type)
        if res:
            origins = {l.origin for l in chain(*res.values())}
            for line in self.lines:
                if line in origins:
                    continue
                invoice_line = InvoiceLine()
                if line.type == 'line':
                    invoice_line.type = 'comment'
                else:
                    invoice_line.type = line.type
                invoice_line.description = line.description
                invoice_line.note = line.note
                invoice_line.origin = line
                invoice_line.sequence = line.sequence
                res[line.id] = [invoice_line]
        return res

    @classmethod
    def draft(cls, sales):
        pool = Pool()
        SaleLine = pool.get('sale.line')
        WBS = pool.get('work.breakdown.structure')
        super(Sale, cls).draft(sales)
        to_write = []
        wbs_to_check = []
        for sale in sales:
            for line in sale.lines:
                if line.wbs:
                    wbs_to_check.append(line.wbs)
                    to_write.append(line)
        if to_write:
            SaleLine.write(to_write, {'wbs': None})
        to_delete = []
        for wbs in wbs_to_check:
            if not wbs.sale_lines:
                to_delete.append(wbs)
        if to_delete:
            with Transaction().set_context(_check_access=False):
                WBS.delete(to_delete)

    @classmethod
    def quote(cls, sales):
        super(Sale, cls).quote(sales)
        for sale in sales:
            with Transaction().set_context(_check_access=False):
                sale.create_wbs_from_lines(sale.lines_tree, sale.wbs_tree)

    def create_wbs_from_lines(self, lines_tree, wbs_tree):
        wbs_by_description = {x.description: x for x in wbs_tree}
        for line in lines_tree:
            wbs_parent = line.parent.wbs if line.parent else None
            if not line.wbs:
                wbs = wbs_by_description.get(line.description)
                if not wbs:
                    wbs = line.get_work_breakdown_structure(wbs_parent)
                    wbs.save()
                line.wbs = wbs
                line.save()
            elif wbs_parent and line.wbs.parent != wbs_parent:
                line.wbs.parent = wbs_parent
                line.wbs.save()
            if line.childs:
                self.create_wbs_from_lines(line.childs, line.wbs.childs)

    @classmethod
    def copy(cls, sales, default=None):
        pool = Pool()
        SaleLine = pool.get('sale.line')
        if default is None:
            default = {}
        default['lines'] = []
        new_sales = super(Sale, cls).copy(sales, default=default)
        for sale, new_sale in zip(sales, new_sales):
            new_default = default.copy()
            new_default['sale'] = new_sale.id
            SaleLine.copy(sale.lines_tree, default=new_default)
        return new_sales


class SaleLine(ChapterMixin):
    __name__ = 'sale.line'

    parent = fields.Many2One('sale.line', 'Parent', select=True,
        left="left", right="right", ondelete='CASCADE', domain=[
            ('sale', '=', Eval('sale')),
            # compatibility with sale_subchapters
            ('type', 'in', ['title', 'subtitle']),
            ], depends=['sale'])
    left = fields.Integer('Left', required=True, select=True)
    right = fields.Integer('Right', required=True, select=True)
    childs = fields.One2Many('sale.line', 'parent', 'Childs', domain=[
            ('sale', '=', Eval('sale')),
            ],
        depends=['sale'])
    wbs = fields.Many2One('work.breakdown.structure', 'WBS', select=True,
        readonly=True, domain=[
            ('type', '=', Eval('type')),
            ('product', '=', Eval('product')),
            ('unit', '=', Eval('unit')),
            ],
        depends=['type', 'product', 'unit'])

    @classmethod
    def __setup__(cls):
        super(SaleLine, cls).__setup__()
        if hasattr(cls, '_allow_modify_after_draft'):
            cls._allow_modify_after_draft.add('wbs')
        for field_name in ['product', 'quantity', 'unit', 'unit_price']:
            field = getattr(cls, field_name)
            # Remove readonly state defined on sale
            field.states.update({'readonly': False})

    @staticmethod
    def default_left():
        return 0

    @staticmethod
    def default_right():
        return 0

    def get_invoice_line(self, invoice_type):
        'Ensure that all lines have the sequence filled'
        lines = super(SaleLine, self).get_invoice_line(invoice_type)
        for line in lines:
            line.sequence = self.sequence
        return lines

    def get_amount(self, name):
        if self.parent and (
                self.type == 'subtotal' and self.parent.type == 'title' or
                self.type == 'subsubtotal' and self.parent.type == 'subtitle'):

            def get_amount_rec(parent):
                subtotal = Decimal(0)
                for line2 in parent.childs:
                    if line2.childs:
                        subtotal += get_amount_rec(line2)
                    if line2.type == 'line':
                        subtotal += line2.sale.currency.round(
                            Decimal(str(line2.quantity)) * line2.unit_price)
                    elif line2.type == self.type:
                        if self == line2:
                            return subtotal
                        subtotal = Decimal(0)
                return subtotal

            return get_amount_rec(self.parent)
        return super(SaleLine, self).get_amount(name)

    def get_subtotal(self, sequence):
        line = super(SaleLine, self).get_subtotal(sequence)
        if self.childs:
            line.parent = self
            line.sequence = 9999
        return line

    @classmethod
    def get_1st_level_chapters(cls, records):
        for sale in {l.sale for l in records}:
            yield sale.lines_tree

    def get_work_breakdown_structure(self, parent):
        pool = Pool()
        WBS = pool.get('work.breakdown.structure')
        wbs = WBS()
        wbs.description = self.description
        wbs.sale_lines = [self]
        wbs.type = self.type
        wbs.parent = parent
        wbs.sequence = self.sequence
        wbs.product = self.product
        wbs.unit = self.unit
        return wbs

    @classmethod
    def copy(cls, lines, default=None):
        if default is None:
            default = {}
        default['wbs'] = None
        default['childs'] = []
        new_lines = []
        for line in lines:
            new_line, = super(SaleLine, cls).copy([line], default)
            new_lines.append(new_line)
            new_default = default.copy()
            new_default['parent'] = new_line.id
            cls.copy(line.childs, default=new_default)
        return new_lines
