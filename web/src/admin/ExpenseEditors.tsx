import { DatePicker, Form, Input, InputNumber, Modal, message } from 'antd'
import dayjs from 'dayjs'
import { useState } from 'react'

import { writeExpense, type ExpenseEntry, type ExpenseRule, type FxRate } from './costsApi'

interface Props<T> { row: T | null; onClose: () => void; onSaved: () => void }

interface EntryValues { name: string; category: string; amount: string; currency: string; period_start?: dayjs.Dayjs; period_end?: dayjs.Dayjs; paid_on?: dayjs.Dayjs; reason: string }

export function EditEntry({ row, onClose, onSaved }: Props<ExpenseEntry>) {
  const [saving, setSaving] = useState(false)
  async function submit(values: EntryValues) {
    if (!row) return
    setSaving(true)
    try {
      await writeExpense(`expenses/${row.id}/details`, 'PATCH', {
        version: row.version, name: values.name.trim(), category: values.category.trim(), amount: String(values.amount), currency: values.currency.toUpperCase(),
        ...(row.kind === 'fixed' && row.rule_id === null ? { period_start: values.period_start?.format('YYYY-MM-DD'), period_end: values.period_end?.format('YYYY-MM-DD') } : {}),
        ...(row.status === 'paid' ? { paid_on: values.paid_on?.format('YYYY-MM-DD') } : {}),
        reason: values.reason.trim(),
      })
      message.success('账目修订已保存并留有审计记录')
      onClose(); onSaved()
    } catch (error) { message.error(error instanceof Error ? error.message : '修订失败') }
    finally { setSaving(false) }
  }
  return <Modal title="修订账目" open={Boolean(row)} onCancel={onClose} onOk={() => void document.getElementById('edit-entry-submit')?.click()} okButtonProps={{ loading: saving, disabled: saving }} destroyOnHidden>
    {row && <Form key={row.id} layout="vertical" onFinish={values => void submit(values)} initialValues={{ name: row.name, category: row.category, amount: row.amount, currency: row.currency, period_start: row.period_start ? dayjs(row.period_start) : undefined, period_end: row.period_end ? dayjs(row.period_end) : undefined, paid_on: row.paid_on ? dayjs(row.paid_on) : undefined }}>
      <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input maxLength={200} /></Form.Item>
      <Form.Item name="category" label="类别" rules={[{ required: true }]}><Input maxLength={80} /></Form.Item>
      <Form.Item name="amount" label="金额" rules={[{ required: true }]}><InputNumber<string> stringMode min="0.000001" precision={6} style={{ width: '100%' }} /></Form.Item>
      <Form.Item name="currency" label="币种" rules={[{ required: true }, { pattern: /^[A-Z]{3}$/ }]}><Input maxLength={3} /></Form.Item>
      {row.kind === 'fixed' && row.rule_id === null && <><Form.Item name="period_start" label="覆盖起始日" rules={[{ required: true }]}><DatePicker /></Form.Item><Form.Item name="period_end" label="覆盖终止日（不含）" rules={[{ required: true }]}><DatePicker /></Form.Item></>}
      {row.status === 'paid' && row.paid_at === null && <Form.Item name="paid_on" label="付款日期" rules={[{ required: true }]}><DatePicker /></Form.Item>}
      <Form.Item name="reason" label="修订原因" rules={[{ required: true }]}><Input.TextArea maxLength={500} /></Form.Item>
      <button id="edit-entry-submit" type="submit" hidden />
    </Form>}
  </Modal>
}

interface RuleValues { name: string; category: string; amount: string; currency: string; stop_before?: dayjs.Dayjs; reminder_days: number; reason: string }

export function EditRule({ row, onClose, onSaved }: Props<ExpenseRule>) {
  const [saving, setSaving] = useState(false)
  async function submit(values: RuleValues) {
    if (!row) return
    setSaving(true)
    try {
      await writeExpense(`expense-rules/${row.id}`, 'PATCH', { version: row.version, name: values.name.trim(), category: values.category.trim(), amount: String(values.amount), currency: values.currency.toUpperCase(), stop_before: values.stop_before?.format('YYYY-MM-DD') ?? null, reminder_days: values.reminder_days, reason: values.reason.trim() })
      message.success('规则修订已保存；已生成账目保留旧版本')
      onClose(); onSaved()
    } catch (error) { message.error(error instanceof Error ? error.message : '修订失败') }
    finally { setSaving(false) }
  }
  return <Modal title="修订周期规则" open={Boolean(row)} onCancel={onClose} onOk={() => void document.getElementById('edit-rule-submit')?.click()} okButtonProps={{ loading: saving, disabled: saving }} destroyOnHidden>
    {row && <Form key={row.id} layout="vertical" onFinish={values => void submit(values)} initialValues={{ name: row.name, category: row.category, amount: row.amount, currency: row.currency, stop_before: row.stop_before ? dayjs(row.stop_before) : undefined, reminder_days: row.reminder_days }}>
      <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input maxLength={200} /></Form.Item><Form.Item name="category" label="类别" rules={[{ required: true }]}><Input maxLength={80} /></Form.Item><Form.Item name="amount" label="后续每期金额" rules={[{ required: true }]}><InputNumber<string> stringMode min="0.000001" precision={6} style={{ width: '100%' }} /></Form.Item><Form.Item name="currency" label="币种" rules={[{ required: true }, { pattern: /^[A-Z]{3}$/ }]}><Input maxLength={3} /></Form.Item><Form.Item name="stop_before" label="停用日期（该日起不再生成）"><DatePicker /></Form.Item><Form.Item name="reminder_days" label="提前提醒天数" rules={[{ required: true }]}><InputNumber min={0} max={365} /></Form.Item><Form.Item name="reason" label="修订原因" rules={[{ required: true }]}><Input.TextArea maxLength={500} /></Form.Item><button id="edit-rule-submit" type="submit" hidden />
    </Form>}
  </Modal>
}

interface RateValues { rate_to_usd: string; source: string; reason: string }

export function EditRate({ row, onClose, onSaved }: Props<FxRate>) {
  const [saving, setSaving] = useState(false)
  async function submit(values: RateValues) {
    if (!row) return
    setSaving(true)
    try {
      await writeExpense('expense-rates', 'PUT', { currency: row.currency, effective_on: row.effective_on, rate_to_usd: String(values.rate_to_usd), source: values.source.trim(), version: row.version, reason: values.reason.trim() })
      message.success('汇率修订已保存')
      onClose(); onSaved()
    } catch (error) { message.error(error instanceof Error ? error.message : '修订失败') }
    finally { setSaving(false) }
  }
  return <Modal title={`修订 ${row?.currency ?? ''} 汇率`} open={Boolean(row)} onCancel={onClose} onOk={() => void document.getElementById('edit-rate-submit')?.click()} okButtonProps={{ loading: saving, disabled: saving }} destroyOnHidden>
    {row && <Form key={row.id} layout="vertical" onFinish={values => void submit(values)} initialValues={{ rate_to_usd: row.rate_to_usd, source: row.source }}><p>生效日：{row.effective_on}</p><Form.Item name="rate_to_usd" label="1 原币兑 USD" rules={[{ required: true }]}><InputNumber<string> stringMode min="0.000000000001" precision={12} style={{ width: '100%' }} /></Form.Item><Form.Item name="source" label="来源" rules={[{ required: true }]}><Input maxLength={200} /></Form.Item><Form.Item name="reason" label="修订原因" rules={[{ required: true }]}><Input.TextArea maxLength={500} /></Form.Item><button id="edit-rate-submit" type="submit" hidden /></Form>}
  </Modal>
}
