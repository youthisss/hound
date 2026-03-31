"use client";

import { useTable } from "@refinedev/antd";
import { Table, Typography, Card, Button, Form, Input } from "antd";
import { PlusOutlined, SearchOutlined, ShopOutlined } from "@ant-design/icons";
import { EditButton, DeleteButton, ShowButton, Breadcrumb, CreateButton } from "@refinedev/antd";
import { useSearchParams } from "next/navigation";

const { Title, Text } = Typography;

export default function VendorList() {
  const searchParams = useSearchParams();
  const q = searchParams.get("q") || "";
  const { tableProps, searchFormProps } = useTable({
    syncWithLocation: true,
    filters: {
      permanent: q
        ? [
            {
              field: "q",
              operator: "eq",
              value: q,
            },
          ]
        : [],
    },
    onSearch: (values: any) => {
      return [
        {
          field: "q",
          operator: "eq",
          value: values.q,
        },
      ];
    },
  });

  return (
    <div style={{ padding: '32px 40px', maxWidth: 1400, margin: "0 auto", minHeight: 'calc(100vh - 64px)' }}>
      <div style={{ marginBottom: 16 }}><Breadcrumb /></div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 32 }}>
        <div>
          <Title level={2} style={{ margin: '0 0 8px 0', fontWeight: 700 }}>
            Vendor Master Data
          </Title>
        </div>
        <CreateButton
          type="default"
          icon={<PlusOutlined />}
          style={{ height: '40px', padding: '0 20px', fontWeight: 500, borderRadius: '6px' }}
        >
          Add Vendor
        </CreateButton>
      </div>

      <Card variant="borderless" className="no-padding-card" style={{ borderRadius: '12px', overflow: 'hidden', boxShadow: '0 4px 12px rgba(0,0,0,0.05)' }}>
        <div style={{ padding: '16px', borderBottom: '1px solid var(--ant-color-border-secondary)' }}>
          <Form {...(searchFormProps as any)} layout="inline" onValuesChange={() => searchFormProps.form?.submit()}>
            <Form.Item name="q" style={{ margin: 0 }}>
              <Input
                prefix={<SearchOutlined style={{ color: "var(--ant-color-text-secondary)", marginRight: 8 }} />}
                placeholder="Search contracts, vendors, or mills..."
                allowClear
                style={{ width: 360, borderRadius: "8px" }}
                onPressEnter={() => searchFormProps.form?.submit()}
              />
            </Form.Item>
          </Form>
        </div>
        <Table
          {...(tableProps as any)}
          rowKey="id"
          pagination={{
            ...(tableProps.pagination || {}),
            position: undefined,
            style: { padding: '16px' },
            showSizeChanger: true,
            pageSizeOptions: ["10", "20", "50", "100"]
          } as any}
          scroll={{ x: 'max-content' }}
        >
          <Table.Column dataIndex="id" title="ID" width={80} />
          <Table.Column dataIndex="code" title="Vendor Code" width={200} render={val => <Text strong>{val}</Text>} />
          <Table.Column dataIndex="name" title="Vendor Name" />
          <Table.Column
            title="Actions"
            dataIndex="actions"
            width={240}
            align="center"
            render={(_, record: any) => (
              <div style={{ display: "flex", gap: "8px", justifyContent: "center", flexWrap: "wrap" }}>
                <ShowButton size="middle" recordItemId={record.id} />
                <EditButton size="middle" recordItemId={record.id} />
                <DeleteButton size="middle" recordItemId={record.id} />
              </div>
            )}
          />
        </Table>
      </Card>
    </div>
  );
}
