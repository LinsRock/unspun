import { Button, DatePicker, Form, Input, InputNumber, Modal, Select, message } from 'antd'
import dayjs from 'dayjs'
import { useState } from 'react'

import { writeExpense, type ExpenseRule } from './costsApi'

interface FormValues { name: string; category: string; amount: string; currency: string; kind: 'fixed' | 'topup'; period_start?: dayjs.Dayjs; period_end?: dayjs.Dayjs; paid_on?: dayjs.Dayjs; reason: string }

export default function ExpenseForm({ onSaved }: { onSaved: () => void }) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<FormValues>()
  const kind = Form.useWatch('kind', form)

  async function submit(values: FormValues) {
    setSaving(true)
    try {
      await writeExpense('expenses', 'POST', {
        name: values.name.trim(), category: values.category.trim(), amount: String(values.amount), currency: values.currency.toUpperCase(), kind: values.kind,
        period_start: values.kind === 'fixed' ? values.period_start?.format('YYYY-MM-DD') : null,
        period_end: values.kind === 'fixed' ? values.period_end?.format('YYYY-MM-DD') : null,
        paid_on: values.paid_on?.format('YYYY-MM-DD') ?? null, reason: values.reason.trim(),
      })
      message.success('账目已保存')
      form.resetFields()
      setOpen(false)
      onSaved()
    } catch (error) { message.error(error instanceof Error ? error.message : '保存失败') }
    finally { setSaving(false) }
  }

  return <>
    <Button type="primary" onClick={() => setOpen(true)}>新增账目</Button>
    <Modal title="新增账目" open={open} onCancel={() => setOpen(false)} onOk={() => void form.submit()} okButtonProps={{ loading: saving, disabled: saving }} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={values => void submit(values)} initialValues={{ currency: 'USD', kind: 'fixed' }}>
        <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input maxLength={200} /></Form.Item>
        <Form.Item name="category" label="类别" rules={[{ required: true }]}><Input maxLength={80} /></Form.Item>
        <Form.Item name="amount" label="金额" rules={[{ required: true }]}><InputNumber<string> stringMode min="0.000001" precision={6} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="currency" label="币种" rules={[{ required: true }, { pattern: /^[A-Z]{3}$/, message: '请输入三位大写币种代码' }]}><Input maxLength={3} /></Form.Item>
        <Form.Item name="kind" label="类型"><Select options={[{ value: 'fixed', label: '固定费用' }, { value: 'topup', label: '预付充值' }]} /></Form.Item>
        {kind === 'fixed' && <><Form.Item name="period_start" label="覆盖起始日" rules={[{ required: true }]}><DatePicker style={{ width: '100%' }} /></Form.Item><Form.Item name="period_end" label="覆盖终止日（不含）" rules={[{ required: true }, { validator: (_, value) => !value || !form.getFieldValue('period_start') || value.isAfter(form.getFieldValue('period_start')) ? Promise.resolve() : Promise.reject(new Error('终止日须晚于起始日')) }]}><DatePicker style={{ width: '100%' }} /></Form.Item></>}
        <Form.Item name="paid_on" label="实际付款日期" rules={kind === 'topup' ? [{ required: true, message: '充值必须填写付款日期' }] : []}><DatePicker style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="reason" label="记录原因" rules={[{ required: true }]}><Input.TextArea maxLength={500} /></Form.Item>
      </Form>
    </Modal>
  </>
}

interface RuleValues { name: string; category: string; amount: string; currency: string; cadence: 'once' | 'monthly' | 'yearly'; anchor_date: dayjs.Dayjs; once_end?: dayjs.Dayjs; reminder_days: number; reason: string }

export function RuleForm({ onSaved }: { onSaved: () => void }) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<RuleValues>()
  const cadence = Form.useWatch('cadence', form)
  async function submit(values: RuleValues) {
    setSaving(true)
    try {
      const rule = await writeExpense<ExpenseRule>('expense-rules', 'POST', { name: values.name.trim(), category: values.category.trim(), amount: String(values.amount), currency: values.currency.toUpperCase(), cadence: values.cadence, anchor_date: values.anchor_date.format('YYYY-MM-DD'), once_end: values.cadence === 'once' ? values.once_end?.format('YYYY-MM-DD') : null, reminder_days: values.reminder_days, reason: values.reason.trim() })
      try {
        await writeExpense(`expense-rules/${rule.id}/generate`, 'POST', { through: dayjs().add(1, 'year').format('YYYY-MM-DD') })
        message.success('周期规则与未来一年账目已保存')
      } catch { message.warning('规则已保存，但账目生成失败；请在规则列表重试。') }
      form.resetFields()
      setOpen(false)
      onSaved()
    } catch (error) { message.error(error instanceof Error ? error.message : '保存失败') }
    finally { setSaving(false) }
  }
  return <><Button onClick={() => setOpen(true)}>新增周期规则</Button><Modal title="新增周期规则" open={open} onCancel={() => setOpen(false)} onOk={() => void form.submit()} okButtonProps={{ loading: saving, disabled: saving }} destroyOnHidden><Form form={form} layout="vertical" initialValues={{ currency: 'USD', cadence: 'monthly', reminder_days: 7 }} onFinish={values => void submit(values)}>
    <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input maxLength={200} /></Form.Item>
    <Form.Item name="category" label="类别" rules={[{ required: true }]}><Input maxLength={80} /></Form.Item>
    <Form.Item name="amount" label="每期金额" rules={[{ required: true }]}><InputNumber<string> stringMode min="0.000001" precision={6} style={{ width: '100%' }} /></Form.Item>
    <Form.Item name="currency" label="币种" rules={[{ required: true }, { pattern: /^[A-Z]{3}$/ }]}><Input maxLength={3} /></Form.Item>
    <Form.Item name="cadence" label="周期"><Select options={[{ value: 'once', label: '一次性' }, { value: 'monthly', label: '每月' }, { value: 'yearly', label: '每年' }]} /></Form.Item>
    <Form.Item name="anchor_date" label="首期起始日" rules={[{ required: true }]}><DatePicker style={{ width: '100%' }} /></Form.Item>
    {cadence === 'once' && <Form.Item name="once_end" label="覆盖终止日（不含）" rules={[{ required: true }, { validator: (_, value) => !value || !form.getFieldValue('anchor_date') || value.isAfter(form.getFieldValue('anchor_date')) ? Promise.resolve() : Promise.reject(new Error('终止日须晚于起始日')) }]}><DatePicker style={{ width: '100%' }} /></Form.Item>}
    <Form.Item name="reminder_days" label="提前提醒天数" rules={[{ required: true }]}><InputNumber min={0} max={365} style={{ width: '100%' }} /></Form.Item>
    <Form.Item name="reason" label="记录原因" rules={[{ required: true }]}><Input.TextArea maxLength={500} /></Form.Item>
  </Form></Modal></>
}

interface RateValues { currency: string; effective_on: dayjs.Dayjs; rate_to_usd: string; source: string; reason: string }

export function RateForm({ onSaved }: { onSaved: () => void }) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<RateValues>()
  async function submit(values: RateValues) {
    setSaving(true)
    try {
      await writeExpense('expense-rates', 'PUT', { currency: values.currency.toUpperCase(), effective_on: values.effective_on.format('YYYY-MM-DD'), rate_to_usd: String(values.rate_to_usd), source: values.source.trim(), reason: values.reason.trim() })
      message.success('汇率已保存')
      form.resetFields()
      setOpen(false)
      onSaved()
    } catch (error) { message.error(error instanceof Error ? error.message : '保存失败') }
    finally { setSaving(false) }
  }
  return <><Button onClick={() => setOpen(true)}>新增汇率</Button><Modal title="新增汇率" open={open} onCancel={() => setOpen(false)} onOk={() => void form.submit()} okButtonProps={{ loading: saving, disabled: saving }} destroyOnHidden><Form form={form} layout="vertical" onFinish={values => void submit(values)}>
    <Form.Item name="currency" label="原币" rules={[{ required: true }, { pattern: /^[A-Z]{3}$/, message: '请输入三位大写币种代码' }]}><Input maxLength={3} /></Form.Item>
    <Form.Item name="effective_on" label="生效日" rules={[{ required: true }]}><DatePicker style={{ width: '100%' }} /></Form.Item>
    <Form.Item name="rate_to_usd" label="1 原币兑 USD" rules={[{ required: true }]}><InputNumber<string> stringMode min="0.000000000001" precision={12} style={{ width: '100%' }} /></Form.Item>
    <Form.Item name="source" label="汇率来源" rules={[{ required: true }]}><Input maxLength={200} /></Form.Item>
    <Form.Item name="reason" label="记录原因" rules={[{ required: true }]}><Input.TextArea maxLength={500} /></Form.Item>
  </Form></Modal></>
}
