"use client";

import { useForm, useSelect } from "@refinedev/antd";
import { Breadcrumb, ListButton, RefreshButton, SaveButton } from "@refinedev/antd";
import { Form, Input, Select, InputNumber, DatePicker, Row, Col, Typography, Space, Card, Divider } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import AgreementHistoryPanel from "@/components/contracts/AgreementHistoryPanel";

export default function DedicatedVarEdit() {
  const { formProps, saveButtonProps, query } = useForm({
    meta: {
      populate: ["vendor", "mill", "origin_zone", "dest_zone", "mot", "uom"],
    }
  });

  const { selectProps: vendorSelectProps } = useSelect({ resource: "vendors", optionLabel: "name" });
  const { selectProps: millSelectProps } = useSelect({ resource: "mills", optionLabel: "name" });
  const { selectProps: zoneSelectProps } = useSelect({ resource: "zones", optionLabel: "name" });
  const { selectProps: motSelectProps } = useSelect({ resource: "mots", optionLabel: "name" });
  const { selectProps: uomSelectProps } = useSelect({ resource: "uoms", optionLabel: "name" });

  const customFormProps = {
    ...formProps,
    initialValues: {
      ...formProps.initialValues,
      validity_start: formProps.initialValues?.validity_start ? dayjs(formProps.initialValues.validity_start) : null,
      validity_end: formProps.initialValues?.validity_end ? dayjs(formProps.initialValues.validity_end) : null,
    }
  };

  const contractId = query?.data?.data?.id;

  const formatIDR = (value: number | string | undefined) => {
    if (!value) return '';
    return `Rp ${value}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  };

  const parseIDR = (value: string | undefined) => {
    if (!value) return 0;
    return value.replace(/\Rp\s?|(,*)/g, '') as unknown as number;
  };

  const handleOnFinish = async (values: any) => {
    const payload = { ...values };

    payload.validity_start = values.validity_start ? (dayjs.isDayjs(values.validity_start) ? values.validity_start.toISOString() : new Date(values.validity_start).toISOString()) : null;
    payload.validity_end = values.validity_end ? (dayjs.isDayjs(values.validity_end) ? values.validity_end.toISOString() : new Date(values.validity_end).toISOString()) : null;

    // Clean up nested objects to prevent GORM association update errors
    delete payload.mill;
    delete payload.vendor;
    delete payload.product;
    delete payload.mot;
    delete payload.uom;
    delete payload.origin_zone;
    delete payload.dest_zone;
    delete payload.created_at;
    delete payload.updated_at;
    delete payload.deleted_at;

    // Convert stringized numbers to actual numbers
    ['distance', 'payload', 'loading_cost', 'unloading_cost', 'cost_idr', 'cost_per_kg', 'cost_per_ton', 'running_cost_idr', 'running_cost_usd', 'cost_jan', 'cost_feb', 'cost_mar', 'cost_apr', 'cost_may', 'cost_jun', 'fix_cost', 'distributed_cost', 'cargo_carried', 'unit_cost', 'cost_per_kg_km'].forEach(key => {
      if (payload[key] !== undefined && payload[key] !== null && typeof payload[key] === 'string') {
        const val = payload[key].replace(/Rp\s?|(,*)/g, '');
        payload[key] = val ? Number(val) : 0;
      }
    });

    await formProps.onFinish?.(payload);
  };

  return (
    <div style={{ padding: '32px 40px', maxWidth: 1400, margin: "0 auto" }}>
      <div style={{ marginBottom: 16 }}><Breadcrumb /></div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Space>
          <ListButton icon={<ArrowLeftOutlined />} shape="circle" type="text" hideText />
          <Typography.Title level={2} style={{ margin: 0, fontWeight: 700 }}>Edit Dedicated Var Contract</Typography.Title>
        </Space>
      </div>

      <Row gutter={[24, 24]} align="stretch" justify="center">
        <Col xs={24} lg={14}>
          <Card variant="borderless" style={{ borderRadius: '12px', boxShadow: '0 4px 12px rgba(0,0,0,0.05)' }}>
            <Form {...customFormProps} onFinish={handleOnFinish} layout="vertical">

              <Divider titlePlacement="start">General Information</Divider>
              <Row gutter={16} align="bottom">
                <Col span={12}>
                  <Form.Item label="Vendor" name="vendor_id" rules={[{ required: true }]}>
                    <Select {...vendorSelectProps} placeholder="Select vendor" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="Mill" name="mill_id" rules={[{ required: true }]}>
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

              <Divider titlePlacement="start">Routing & Operations</Divider>
              <Row gutter={16} align="bottom">
                <Col span={12}>
                  <Form.Item label="Origin Zone" name="origin_zone_id">
                    <Select {...zoneSelectProps} placeholder="Select Origin" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="Destination Zone" name="dest_zone_id">
                    <Select {...zoneSelectProps} placeholder="Select Destination" />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16} align="bottom">
                <Col span={12}>
                  <Form.Item label="MOT" name="mot_id">
                    <Select {...motSelectProps} placeholder="Select Mode of Transport" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="Distance (KM)" name="distance">
                    <InputNumber style={{ width: '100%' }} placeholder="0" />
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
                  <Form.Item label="Payload" name="payload">
                    <InputNumber style={{ width: '100%' }} placeholder="0" />
                  </Form.Item>
                </Col>
              </Row>

              <Divider titlePlacement="start">Financials</Divider>
              <Row gutter={16} align="bottom">
                <Col span={12}>
                  <Form.Item label="Cost (IDR)" name="cost_idr">
                    <InputNumber style={{ width: '100%' }} formatter={formatIDR} parser={parseIDR} placeholder="0" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="Cost / KG" name="cost_per_kg">
                    <InputNumber style={{ width: '100%' }} formatter={formatIDR} parser={parseIDR} placeholder="0" />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16} align="bottom">
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
        </Col>
        <Col xs={24} lg={10}>
          <AgreementHistoryPanel
            contractId={contractId as number}
            resourceSuffix="dedicated-var"
            entityTypeDb="contract_dedicated_var"
          />
        </Col>
      </Row>
    </div>
  );
}


