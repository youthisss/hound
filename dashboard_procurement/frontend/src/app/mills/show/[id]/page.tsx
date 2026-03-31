"use client";

import React, { useState, useEffect } from "react";
import { useShow, useList } from "@refinedev/core";
import { Breadcrumb, ListButton, EditButton } from "@refinedev/antd";
import { Typography, Row, Col, Card, Tag, Table, Empty, Descriptions, Statistic, Space, Flex, Spin, Tabs, Button, theme } from "antd";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080/api/v1";
import {
  ArrowRightOutlined,
  CarOutlined,
  ArrowLeftOutlined,
  DollarOutlined,
  TeamOutlined,
  HistoryOutlined,
  SolutionOutlined,
  NodeIndexOutlined
} from "@ant-design/icons";
import { App, Form, Input, Divider, Timeline } from "antd";
import { apiClient } from "@/lib/api-client";

const { Title, Text } = Typography;

const formatIDR = (val: any) => {
  if (!val) return "-";
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(val);
};

const formatDate = (val: any) => val ? String(val).split("T")[0] : "-";

export default function MillShow() {
  const { token } = theme.useToken(); // Hook untuk Dark/Light mode
  const { query } = useShow({});
  const { data, isLoading } = query;
  const record = data?.data;
  const millId = record?.id;

  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [submittingNote, setSubmittingNote] = useState(false);
  const [auditLogs, setAuditLogs] = useState<any[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);

  const { query: fixQuery } = useList({
    resource: "contracts/dedicated-fix",
    filters: millId ? [{ field: "mill_id", operator: "eq", value: millId }] : [],
    pagination: { mode: "off" },
    meta: { populate: ["vendor", "mill", "product", "mot", "uom"] },
    queryOptions: { enabled: !!millId }
  });
  const { query: varQuery } = useList({
    resource: "contracts/dedicated-var",
    filters: millId ? [{ field: "mill_id", operator: "eq", value: millId }] : [],
    pagination: { mode: "off" },
    meta: { populate: ["vendor", "mill", "product", "origin_zone", "dest_zone", "mot", "uom"] },
    queryOptions: { enabled: !!millId }
  });
  const { query: oncallQuery } = useList({
    resource: "contracts/oncall",
    filters: millId ? [{ field: "mill_id", operator: "eq", value: millId }] : [],
    pagination: { mode: "off" },
    meta: { populate: ["vendor", "mill", "product", "origin_zone", "dest_zone", "mot", "uom"] },
    queryOptions: { enabled: !!millId }
  });

  const fixContracts = fixQuery.data?.data || [];
  const varContracts = varQuery.data?.data || [];
  const oncallContracts = oncallQuery.data?.data || [];
  const allContracts = [...fixContracts, ...varContracts, ...oncallContracts];
  const contractsLoading = fixQuery.isLoading || varQuery.isLoading || oncallQuery.isLoading;

  const fetchLogs = async () => {
    if (!millId) return;
    setLogsLoading(true);
    try {
      const { data } = await apiClient.get(`${API_URL}/audit/mill/${millId}`);
      setAuditLogs(Array.isArray(data) ? data : []);
    } catch (e) { console.error(e); }
    setLogsLoading(false);
  };

  useEffect(() => {
    if (millId) fetchLogs();
  }, [millId]);

  const handleNoteSubmit = async (values: any) => {
    if (!millId) return;
    setSubmittingNote(true);
    try {
      await apiClient.patch(`${API_URL}/mills/${millId}/agreement`, values);
      message.success("Negotiation note added successfully!");
      form.resetFields();
      fetchLogs();
    } catch (error) {
      message.error("Failed to add note");
    } finally {
      setSubmittingNote(false);
    }
  };

  // KPI Calculations
  const totalSpend = allContracts.reduce((acc, curr: any) => acc + (Number(curr.cost_idr) || Number(curr.distributed_cost) || 0), 0);
  const activeVendors = Array.from(new Set(allContracts.map(c => c.vendor_id))).length;
  const dedicatedFleet = fixContracts.length + varContracts.length;

  const commonColumns = [
    { title: "SPK", dataIndex: "spk_number", key: "spk", render: (v: any) => <Text strong>{v || "-"}</Text> },
    { title: "Transporter", dataIndex: ["vendor", "name"], key: "vendor" },
    { title: "MOT", dataIndex: ["mot", "name"], key: "mot", render: (v: any) => <Tag color="blue" variant="filled" icon={<CarOutlined />}>{v}</Tag> },
    { title: "Validity", key: "validity", render: (_: any, r: any) => <Text type="secondary" style={{ fontSize: 13 }}>{formatDate(r.validity_start)} to {formatDate(r.validity_end)}</Text> },
    { title: "Status", dataIndex: "status", key: "status", render: (s: any) => <Tag color={s === 'active' ? 'blue' : 'default'} variant="filled">{s?.toUpperCase()}</Tag> }
  ];

  const oncallColumns = [
    { title: "SPK", dataIndex: "spk_number", key: "spk", render: (v: any) => <Text strong>{v || "-"}</Text> },
    { title: "Route", key: "route", render: (_: any, r: any) => <Text>{r.origin_zone?.name} <ArrowRightOutlined style={{ color: token.colorTextSecondary }} /> {r.dest_zone?.name}</Text> },
    { title: "Transporter", dataIndex: ["vendor", "name"], key: "vendor" },
    { title: "Price/Trip", dataIndex: "cost_idr", key: "cost", render: (v: any) => formatIDR(v) },
    { title: "Validity", key: "validity", render: (_: any, r: any) => <Text type="secondary" style={{ fontSize: 13 }}>{formatDate(r.validity_start)} to {formatDate(r.validity_end)}</Text> },
  ];

  if (isLoading) return <div style={{ height: '80vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Spin size="large" /></div>;

  return (
    <div style={{ padding: '32px 40px', maxWidth: 1400, margin: "0 auto", minHeight: '100vh' }}>
      <div style={{ marginBottom: 16 }}><Breadcrumb /></div>

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Space size="middle">
          <ListButton icon={<ArrowLeftOutlined />} shape="circle" type="text" hideText />
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <Title level={4} style={{ margin: 0, fontWeight: 700 }}>
              Mill Control Center: {record?.name}
            </Title>
            <Text type="secondary" style={{ fontSize: 13 }}>Mill Code: {record?.code} • ID: {record?.id}</Text>
          </div>
        </Space>
        <Space>
          <EditButton size="large" style={{ borderRadius: '8px', padding: '0 24px', fontWeight: 600 }} />
        </Space>
      </div>

      <Row gutter={[24, 24]}>
        {/* KPI Row */}
        <Col span={24}>
          <Row gutter={[24, 24]}>
            <Col xs={24} md={8}>
              <Card styles={{ body: { padding: '24px' } }} style={{ borderRadius: 12, border: 'none', background: 'linear-gradient(135deg, #1677ff 0%, #0050b3 100%)', boxShadow: token.boxShadowTertiary }}>
                <Statistic
                  title={<Text style={{ color: 'rgba(255,255,255,0.85)' }}>Total Logistics Spend</Text>}
                  value={totalSpend}
                  formatter={(val) => <span style={{ color: 'white', fontWeight: 700, fontSize: 24 }}>{formatIDR(val)}</span>}
                  prefix={<DollarOutlined style={{ color: 'white' }} />}
                />
              </Card>
            </Col>
            <Col xs={24} md={8}>
              <Card styles={{ body: { padding: '24px' } }} style={{ borderRadius: 12, border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}>
                <Statistic title="Active Serving Vendors" value={activeVendors} prefix={<TeamOutlined style={{ color: token.colorPrimary }} />} />
              </Card>
            </Col>
            <Col xs={24} md={8}>
              <Card styles={{ body: { padding: '24px' } }} style={{ borderRadius: 12, border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}>
                <Statistic title="Total Dedicated Fleet" value={dedicatedFleet} prefix={<CarOutlined style={{ color: token.colorSuccess }} />} />
              </Card>
            </Col>
          </Row>
        </Col>

        {/* Main Content */}
        <Col xs={24} lg={8}>
          <Card styles={{ body: { padding: '24px' } }} style={{ borderRadius: 12, border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}>
            <Descriptions
              title={<span><SolutionOutlined style={{ marginRight: 8, color: token.colorPrimary }} /> Mill Specifications</span>}
              bordered
              size="small"
              column={1}
              styles={{ label: { width: '50%' }, content: { width: '50%' } }}
            >
              <Descriptions.Item label="Mill Code"><Text strong>{record?.code}</Text></Descriptions.Item>
              <Descriptions.Item label="Mill Name">{record?.name}</Descriptions.Item>
            </Descriptions>

            <Divider style={{ borderColor: token.colorSplit }} />
            <Title level={5}>Active Route Distribution</Title>
            <Flex vertical gap={12}>
              {oncallContracts.slice(0, 3).map((r: any) => (
                <div key={r.id} style={{ padding: '8px 12px', backgroundColor: token.colorFillAlter, borderRadius: 8 }}>
                  <Text style={{ fontSize: 12 }}>{r.origin_zone?.name} <ArrowRightOutlined style={{ fontSize: 10, color: token.colorTextSecondary }} /> {r.dest_zone?.name}</Text>
                </div>
              ))}
              {oncallContracts.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No route data" />}
            </Flex>
          </Card>
        </Col>

        <Col xs={24} lg={16}>
          <Card styles={{ body: { padding: '8px 24px 24px 24px' } }} style={{ borderRadius: 12, border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}>
            <Tabs items={[
              {
                key: 'dedicated',
                label: <span><CarOutlined /> Dedicated Fleet <Tag variant="filled" color="blue" style={{ marginLeft: 8 }}>{dedicatedFleet}</Tag></span>,
                children: (
                  <div style={{ padding: '16px 0' }}>
                    <Title level={5}>Fixed Cost Contracts</Title>
                    <Table rowKey="id" dataSource={fixContracts} columns={commonColumns} loading={contractsLoading} size="small" pagination={{ pageSize: 5 }} />
                    <Divider style={{ borderColor: token.colorSplit }} />
                    <Title level={5}>Variable Cost Contracts</Title>
                    <Table rowKey="id" dataSource={varContracts} columns={commonColumns} loading={contractsLoading} size="small" pagination={{ pageSize: 5 }} />
                  </div>
                )
              },
              {
                key: 'oncall',
                label: <span><NodeIndexOutlined /> Oncall Routes <Tag variant="filled" color="orange" style={{ marginLeft: 8 }}>{oncallContracts.length}</Tag></span>,
                children: (
                  <div style={{ padding: '16px 0' }}>
                    <Table rowKey="id" dataSource={oncallContracts} columns={oncallColumns} loading={contractsLoading} size="small" pagination={{ pageSize: 10 }} />
                  </div>
                )
              },
              {
                key: 'negotiation',
                label: <span><HistoryOutlined /> Procurement Tracker</span>,
                children: (
                  <Row gutter={[24, 24]} style={{ marginTop: 16 }}>
                    <Col xs={24} md={10}>
                      <div style={{ backgroundColor: token.colorFillAlter, padding: 20, borderRadius: 8, border: `1px solid ${token.colorBorderSecondary}` }}>
                        <Title level={5} style={{ marginTop: 0 }}>Log Mill Update</Title>
                        <Form form={form} layout="vertical" onFinish={handleNoteSubmit}>
                          <Form.Item name="changed_by" label="Negotiator" rules={[{ required: true }]}>
                            <Input placeholder="e.g. Area Manager" />
                          </Form.Item>
                          <Form.Item name="note" label="Discussion / Decision" rules={[{ required: true }]}>
                            <Input.TextArea rows={4} placeholder="Summarize the site visit or rate discussion..." />
                          </Form.Item>
                          <Button block type="primary" htmlType="submit" loading={submittingNote}>Save Trace</Button>
                        </Form>
                      </div>
                    </Col>
                    <Col xs={24} md={14}>
                      <Title level={5} style={{ marginTop: 0 }}>Timeline</Title>
                      {logsLoading ? <Spin /> : (auditLogs?.length ?? 0) === 0 ? <Empty /> : (
                        <Timeline
                          items={auditLogs.map(log => ({
                            key: log.id,
                            color: log.action === 'agreement_update' ? token.colorPrimary : token.colorTextSecondary,
                            children: (
                              <Flex vertical gap={4} style={{ marginBottom: 16 }}>
                                <div>
                                  <Tag color={log.action === 'agreement_update' ? 'blue' : 'default'} variant="filled">
                                    {log.action.replace("_", " ").toUpperCase()}
                                  </Tag>
                                  <Text type="secondary" style={{ fontSize: 12 }}>{formatDate(log.created_at)} by </Text>
                                  <Text strong>{log.changed_by || 'System'}</Text>
                                </div>
                                {log.agreement_note && (
                                  <div style={{
                                    padding: '8px 12px',
                                    backgroundColor: token.colorBgElevated,
                                    border: `1px solid ${token.colorBorderSecondary}`,
                                    borderRadius: 6,
                                    marginTop: 4
                                  }}>
                                    <Text italic>"{log.agreement_note}"</Text>
                                  </div>
                                )}
                              </Flex>
                            )
                          }))}
                        />
                      )}
                    </Col>
                  </Row>
                )
              }
            ]} />
          </Card>
        </Col>
      </Row>
    </div>
  );
}

