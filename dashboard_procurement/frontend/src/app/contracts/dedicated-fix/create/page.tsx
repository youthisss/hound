"use client";

import { useForm, useSelect } from "@refinedev/antd";
import { Breadcrumb, ListButton, SaveButton } from "@refinedev/antd";
import { Form, Input, Select, InputNumber, DatePicker, Row, Col, Typography, Space, Card, Divider } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import dayjs from "dayjs";

export default function DedicatedFixCreate() {
  const { formProps, saveButtonProps } = useForm();

  const { selectProps: vendorSelectProps } = useSelect({ resource: "vendors", optionLabel: "name" });
  const { selectProps: millSelectProps } = useSelect({ resource: "mills", optionLabel: "name" });
  const { selectProps: motSelectProps } = useSelect({ resource: "mots", optionLabel: "name" });
  const { selectProps: uomSelectProps } = useSelect({ resource: "uoms", optionLabel: "name" });

  const handleOnFinish = async (values: any) => {
    const payload = { ...values };
    
    payload.validity_start = values.validity_start ? (dayjs.isDayjs(values.validity_start) ? values.validity_start.format("YYYY-MM-DD") : values.validity_start) : null;
    payload.validity_end = values.validity_end ? (dayjs.isDayjs(values.validity_end) ? values.validity_end.format("YYYY-MM-DD") : values.validity_end) : null;

    ['fix_cost', 'distributed_cost', 'unit_cost', 'cost_per_kg', 'cost_per_kg_km', 'cargo_carried'].forEach(key => {
      if (payload[key] !== undefined && payload[key] !== null && typeof payload[key] === 'string') {
        const val = payload[key].replace(/Rp\s?|(,*)/g, '');
        payload[key] = val ? Number(val) : 0;
      }
    });

    await formProps.onFinish?.(payload);
  };

  const formatIDR = (value: number | string | undefined) => {
    if (!value) return '';
    return `Rp ${value}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  };
  
  const parseIDR = (value: string | undefined) => {
    if (!value) return 0;
    return value.replace(/\Rp\s?|(,*)/g, '') as unknown as number;
  };

  return (
    <div style={{ padding: '32px 40px', maxWidth: 1400, margin: "0 auto" }}>
      <div style={{ marginBottom: 16 }}><Breadcrumb /></div>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12, justifyContent: 'space-between' }}>
        <Space>
          <ListButton icon={<ArrowLeftOutlined />} shape="circle" type="text" hideText />
          <Typography.Title level={2} style={{ margin: 0, fontWeight: 700 }}>Create Dedicated Fix Contract</Typography.Title>
        </Space>
      </div>

      <div style={{ maxWidth: 800, margin: '0 auto' }}>
        <Card variant="borderless" style={{ borderRadius: '12px', boxShadow: '0 4px 12px rgba(0,0,0,0.05)' }}>
            <Form {...formProps} onFinish={handleOnFinish} layout="vertical">
              
              <Divider titlePlacement="start">General Information</Divider>
              <Row gutter={16} align="bottom">
                <Col span={12}>
                  <Form.Item label="Vendor" name="vendor_id" rules={[{ required: true }]}>
                    <Select {...vendorSelectProps} placeholder="Select vendor" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="Mill / Category" name="mill_id" rules={[{ required: true }]}>
                    <Select {...millSelectProps} placeholder="Select mill" />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16} align="bottom">
                <Col span={12}>
                  <Form.Item label="Area / Category" name="area_category">
                    <Input placeholder="e.g. Category A" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="Proposal / CFAS" name="proposal_cfas">
                    <Input placeholder="e.g. CFAS-001" />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16} align="bottom">
                <Col span={12}>
                  <Form.Item label="SPK Number" name="spk_number">
                    <Input placeholder="e.g. SPK-2026-001" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="FA Number" name="fa_number">
                    <Input placeholder="e.g. FA-001" />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16} align="bottom">
                <Col span={12}>
                  <Form.Item label="Validity Start" name="validity_start">
                    <DatePicker style={{ width: '100%' }} format="DD/MM/YYYY" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="Validity End" name="validity_end">
                    <DatePicker style={{ width: '100%' }} format="DD/MM/YYYY" />
                  </Form.Item>
                </Col>
              </Row>

              <Divider titlePlacement="start">Operational Metrics</Divider>
              <Row gutter={16} align="bottom">
                <Col span={12}>
                  <Form.Item label="MOT (Mode of Transport)" name="mot_id">
                    <Select {...motSelectProps} placeholder="Select MOT" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="License Plate" name="license_plate" rules={[{ required: true }]}>
                    <Input placeholder="e.g. B 1234 XYZ" />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16} align="bottom">
                <Col span={12}>
                  <Form.Item label="UoM" name="uom_id">
                    <Select {...uomSelectProps} placeholder="Select UoM" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="Cargo Carried (MT)" name="cargo_carried">
                    <InputNumber style={{ width: '100%' }} placeholder="0" />
                  </Form.Item>
                </Col>
              </Row>

              <Divider titlePlacement="start">Cost Allocation</Divider>
              <Row gutter={16} align="bottom">
                <Col span={8}>
                  <Form.Item label="Fix Cost" name="fix_cost">
                    <InputNumber style={{ width: '100%' }} formatter={formatIDR} parser={parseIDR} placeholder="0" />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label="Distributed Cost / Unit" name="distributed_cost" rules={[{ required: true }]}>
                    <InputNumber style={{ width: '100%' }} formatter={formatIDR} parser={parseIDR} placeholder="0" />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label="Unit Cost (IDR/MT)" name="unit_cost">
                    <InputNumber style={{ width: '100%' }} formatter={formatIDR} parser={parseIDR} placeholder="0" />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16} align="bottom">
                <Col span={12}>
                  <Form.Item label="Cost / KG" name="cost_per_kg">
                    <InputNumber style={{ width: '100%' }} formatter={formatIDR} parser={parseIDR} placeholder="0" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="Cost / KG / KM" name="cost_per_kg_km">
                    <InputNumber style={{ width: '100%' }} formatter={formatIDR} parser={parseIDR} placeholder="0" />
                  </Form.Item>
                </Col>
              </Row>

              <Form.Item label="Notes" name="notes">
                <Input.TextArea rows={3} placeholder="Additional notes..." />
              </Form.Item>
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 24 }}>
                <SaveButton {...saveButtonProps} size="large" />
              </div>
            </Form>
          </Card>
      </div>
    </div>
  );
}


