#-*- coding:utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2009 Tiny SPRL (<http://tiny.be>). All Rights Reserved
#    d$
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
import time
from openerp import netsvc
from datetime import date, datetime, timedelta
import logging
_logger = logging.getLogger(__name__)
from openerp.osv import fields, osv
from openerp.tools import config, float_compare, float_is_zero
from openerp.tools.translate import _

class hr_salary_rule(osv.osv):
    _inherit = 'hr.salary.rule'
    _columns = {
        'origin_partner': fields.selection((('employee','Empleado'),
                                            ('eps','EPS'),
                                            ('fp','Fondo de Pensiones'),
                                            ('fc','Fondo de Cesantías'),
                                            ('rule','Regla Salarial')),
            'Tipo de tercero', required=True),
        'partner_id':fields.many2one('res.partner', 'Tercero'),
        'origin_analytic_account': fields.selection((('employee','Empleado'),
                                                    ('rule','Regla salarial')),
            'Tipo de Cuenta Analitica'),
    }

    _defaults = {
        'origin_partner': 'employee',
    }

hr_salary_rule()

class hr_payslip_co(osv.osv):
    '''
    Pay Slip
    '''
    _inherit = 'hr.payslip'
    _description = 'Pay Slip'

    _columns = {
    }

    def process_sheet(self, cr, uid, ids, context=None):
        move_pool = self.pool.get('account.move')
        period_pool = self.pool.get('account.period')
        precision = self.pool.get('decimal.precision').precision_get(cr, uid, 'Payroll')

        for slip in self.browse(cr, uid, ids, context=context):
            line_ids = []
            debit_sum = 0.0
            credit_sum = 0.0
            if not slip.period_id:
                ctx = dict(context or {}, account_period_prefer_normal=True)
                search_periods = period_pool.find(cr, uid, slip.date_to, context=ctx)
                period_id = search_periods[0]
            else:
                period_id = slip.period_id.id

            partner_eps_id = slip.employee_id.eps_id.id
            partner_fp_id = slip.employee_id.fp_id.id
            partner_fc_id = slip.employee_id.fc_id.id

            default_partner_id = slip.employee_id.address_home_id.id
            default_analytic_account_id = slip.contract_id.analytic_account_id and slip.contract_id.analytic_account_id.id or False
            name = _('Payslip of %s') % (slip.employee_id.name)
            move = {
                'narration': name,
                'date': slip.date_to,
                'ref': slip.number,
                'journal_id': slip.journal_id.id,
                'period_id': period_id,
            }
            for line in slip.details_by_salary_rule_category:
                amt = slip.credit_note and -line.total or line.total
                if float_is_zero(amt, precision_digits=precision):
                    continue
                debit_account_id = line.salary_rule_id.account_debit.id
                credit_account_id = line.salary_rule_id.account_credit.id

                if line.salary_rule_id.origin_partner == 'employee':
                    partner_id = default_partner_id
                elif line.salary_rule_id.origin_partner == 'eps':
                    partner_id = partner_eps_id
                elif line.salary_rule_id.origin_partner == 'fp':
                    partner_id = partner_fp_id
                elif line.salary_rule_id.origin_partner == 'fc':
                    partner_id = partner_fc_id
                elif line.salary_rule_id.origin_partner == 'rule':
                    partner_id = line.salary_rule_id.partner_id.id
                else:
                    partner_id = default_partner_id

                if line.salary_rule_id.origin_analytic_account == 'employee':
                    analytic_account_id = default_analytic_account_id
                elif line.salary_rule_id.origin_analytic_account == 'rule':
                    analytic_account_id = line.salary_rule_id.analytic_account_id.id
                else:
                    analytic_account_id = False

                if debit_account_id:

                    debit_line = (0, 0, {
                    'name': line.name,
                    'date': slip.date_to,
                    'partner_id': partner_id,
                    'account_id': debit_account_id,
                    'journal_id': slip.journal_id.id,
                    'period_id': period_id,
                    'debit': amt > 0.0 and amt or 0.0,
                    'credit': amt < 0.0 and -amt or 0.0,
                    'analytic_account_id': analytic_account_id,
                    'tax_code_id': line.salary_rule_id.account_tax_id and line.salary_rule_id.account_tax_id.id or False,
                    'tax_amount': line.salary_rule_id.account_tax_id and amt or 0.0,
                })
                    line_ids.append(debit_line)
                    debit_sum += debit_line[2]['debit'] - debit_line[2]['credit']

                if credit_account_id:

                    credit_line = (0, 0, {
                    'name': line.name,
                    'date': slip.date_to,
                    'partner_id': partner_id,
                    'account_id': credit_account_id,
                    'journal_id': slip.journal_id.id,
                    'period_id': period_id,
                    'debit': amt < 0.0 and -amt or 0.0,
                    'credit': amt > 0.0 and amt or 0.0,
                    'analytic_account_id': analytic_account_id,
                    'tax_code_id': line.salary_rule_id.account_tax_id and line.salary_rule_id.account_tax_id.id or False,
                    'tax_amount': line.salary_rule_id.account_tax_id and amt or 0.0,
                })
                    line_ids.append(credit_line)
                    credit_sum += credit_line[2]['credit'] - credit_line[2]['debit']

            if float_compare(credit_sum, debit_sum, precision_digits=precision) == -1:
                acc_id = slip.journal_id.default_credit_account_id.id
                if not acc_id:
                    raise osv.except_osv(_('Configuration Error!'),_('The Expense Journal "%s" has not properly configured the Credit Account!')%(slip.journal_id.name))
                adjust_credit = (0, 0, {
                    'name': _('Adjustment Entry'),
                    'date': slip.date_to,
                    'partner_id': False,
                    'account_id': acc_id,
                    'journal_id': slip.journal_id.id,
                    'period_id': period_id,
                    'debit': 0.0,
                    'credit': debit_sum - credit_sum,
                })
                line_ids.append(adjust_credit)

            elif float_compare(debit_sum, credit_sum, precision_digits=precision) == -1:
                acc_id = slip.journal_id.default_debit_account_id.id
                if not acc_id:
                    raise osv.except_osv(_('Configuration Error!'),_('The Expense Journal "%s" has not properly configured the Debit Account!')%(slip.journal_id.name))
                adjust_debit = (0, 0, {
                    'name': _('Adjustment Entry'),
                    'date': slip.date_to,
                    'partner_id': False,
                    'account_id': acc_id,
                    'journal_id': slip.journal_id.id,
                    'period_id': period_id,
                    'debit': credit_sum - debit_sum,
                    'credit': 0.0,
                })
                line_ids.append(adjust_debit)
            move.update({'line_id': line_ids})
            move_id = move_pool.create(cr, uid, move, context=context)
            self.write(cr, uid, [slip.id], {'move_id': move_id, 'period_id' : period_id, 'state' : 'done'}, context=context)
            if slip.journal_id.entry_posted:
                move_pool.post(cr, uid, [move_id], context=context)
        return True

hr_payslip_co()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
