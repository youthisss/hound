"use client";

import { useForm, Breadcrumb, ListButton, SaveButton } from "@refinedev/antd";
import { Form, Input, Row, Col, Typography, Space, Card } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";

export default function VendorCreate() {
  const { formProps, saveButtonProps } = useForm({});

  return (
    <div style={{ padding: '32px 40px', maxWidth: 1400, margin: "0 auto" }}>
      <div style={{ marginBottom: 16 }}><Breadcrumb /></div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Space>
          <ListButton icon={<ArrowLeftOutlined />} shape="circle" type="text" hideText />
          <Typography.Title level={2} style={{ margin: 0, fontWeight: 700 }}>Create Vendor</Typography.Title>
        </Space>
      </div>

      <div style={{ maxWidth: 800, margin: "0 auto" }}>
        <Card variant="borderless" style={{ borderRadius: "12px", boxShadow: "0 4px 12px rgba(0,0,0,0.05)" }}>
          <Form {...formProps} layout="vertical">
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item label="Vendor Code" name={["code"]} rules={[{ required: true }]}>
                  <Input placeholder="VND-001" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="Tax ID (NPWP)" name={["tax_id"]}>
                  <Input placeholder="00.000.000.0-000.000" />
                </Form.Item>
              </Col>
            </Row>

            <Form.Item label="Vendor Name" name={["name"]} rules={[{ required: true }]}>
              <Input placeholder="PT. Example Logistics" />
            </Form.Item>

            <Row gutter={16}>
              <Col span={12}>
                <Form.Item label="Contact Person" name={["contact_person"]}>
                  <Input placeholder="John Doe" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="Status" name={["status"]} initialValue="active">
                  <Input placeholder="active / inactive" />
                </Form.Item>
              </Col>
            </Row>

            <Row gutter={16}>
              <Col span={12}>
                <Form.Item label="Email" name={["email"]} rules={[{ type: 'email' }]}>
                  <Input placeholder="vendor@example.com" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="Phone" name={["phone"]}>
                  <Input placeholder="+62..." />
                </Form.Item>
              </Col>
            </Row>

            <Form.Item label="Office Address" name={["address"]}>
              <Input.TextArea rows={3} placeholder="Full business address..." />
            </Form.Item>
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 24 }}>
              <SaveButton {...saveButtonProps} size="large" />
            </div>
          </Form>
        </Card>
      </div>
    </div>
  );
}

