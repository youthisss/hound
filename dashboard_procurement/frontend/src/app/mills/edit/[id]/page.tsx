"use client";

import { useForm, Breadcrumb, ListButton, SaveButton } from "@refinedev/antd";
import { Form, Input, Typography, Space, Card } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";

export default function MillEdit() {
  const { formProps, saveButtonProps } = useForm({});

  return (
    <div style={{ padding: '32px 40px', maxWidth: 1400, margin: "0 auto" }}>
      <div style={{ marginBottom: 16 }}><Breadcrumb /></div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Space>
          <ListButton icon={<ArrowLeftOutlined />} shape="circle" type="text" hideText />
          <Typography.Title level={2} style={{ margin: 0, fontWeight: 700 }}>Edit Mill</Typography.Title>
        </Space>
      </div>

      <div style={{ maxWidth: 800, margin: "0 auto" }}>
        <Card variant="borderless" style={{ borderRadius: "12px", boxShadow: "0 4px 12px rgba(0,0,0,0.05)" }}>
          <Form {...formProps} layout="vertical">
            <Form.Item
              label="Mill Code"
              name={["code"]}
              rules={[{ required: true }]}
            >
              <Input placeholder="e.g. MILL-001" />
            </Form.Item>
            <Form.Item
              label="Mill Name"
              name={["name"]}
              rules={[{ required: true }]}
            >
              <Input placeholder="e.g. Mill A" />
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

