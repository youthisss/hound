"use client";

import { useShow, useList, useInvalidate } from "@refinedev/core";
import { Breadcrumb, ListButton, EditButton } from "@refinedev/antd";
import {
  Typography, Row, Col, Card, Tag, Table, Empty, Descriptions,
  Statistic, Space, Flex, Spin, Tabs, Divider, Button, Form, Input, Timeline, App, theme
} from "antd";
import {
  FileDoneOutlined, NodeIndexOutlined,
  CarOutlined, ArrowLeftOutlined, ArrowRightOutlined, DollarOutlined,
  PercentageOutlined, HistoryOutlined, SolutionOutlined,
  EnvironmentOutlined, UserOutlined, MailOutlined, PhoneOutlined, BankOutlined
} from "@ant-design/icons";
import { useState, useEffect } from "react";
import dayjs from "dayjs";
import { apiClient } from "@/lib/api-client";

const { Title, Text } = Typography;
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080/api/v1";

const formatIDR = (val: any) => {
  if (val === undefined || val === null) return "-";
  return new Intl.NumberFormat("id-ID", {
    style: "currency",
    currency: "IDR",
    maximumFractionDigits: 0
  }).format(val);
};

const formatDate = (val: any) => val ? dayjs(val).format("DD/MM/YYYY") : "-";

export default function VendorShow() {
  const { token } = theme.useToken(); // Hook untuk Dark/Light Mode
  const { query } = useShow({});
  const { data: vendorData, isLoading: vendorLoading } = query;
  const vendor = vendorData?.data;
  const vendorId = vendor?.id;

  const { message } = App.useApp();
  const invalidate = useInvalidate();
  const [form] = Form.useForm();
  const [submittingNote, setSubmittingNote] = useState(false);
  const [auditLogs, setAuditLogs] = useState<any[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);

  // Fetch contracts for this vendor using Refine hooks
  const { query: fixQuery } = useList({
    resource: "contracts/dedicated-fix",
    filters: vendorId ? [{ field: "vendor_id", operator: "eq", value: vendorId }] : [],
    pagination: { mode: "off" },
    meta: {
      populate: ["mill", "vendor", "product", "mot", "uom"]
    },
    queryOptions: { enabled: !!vendorId }
  });

  const { query: varQuery } = useList({
    resource: "contracts/dedicated-var",
    filters: vendorId ? [{ field: "vendor_id", operator: "eq", value: vendorId }] : [],
    pagination: { mode: "off" },
    meta: {
      populate: ["mill", "vendor", "product", "origin_zone", "dest_zone", "mot", "uom"]
    },
    queryOptions: { enabled: !!vendorId }
  });

  const { query: oncallQuery } = useList({
    resource: "contracts/oncall",
    filters: vendorId ? [{ field: "vendor_id", operator: "eq", value: vendorId }] : [],
    pagination: { mode: "off" },
    meta: {
      populate: ["mill", "vendor", "product", "origin_zone", "dest_zone", "mot", "uom"]
    },
    queryOptions: { enabled: !!vendorId }
  });


  const fetchLogs = async () => {
    if (!vendorId) return;
    setLogsLoading(true);
    try {
      const { data } = await apiClient.get(`${API_URL}/audit/vendor/${vendorId}`);
      setAuditLogs(Array.isArray(data) ? data : []);
    } catch (e) { console.error(e); }
    setLogsLoading(false);
  };

  useEffect(() => {
    if (vendorId) fetchLogs();
  }, [vendorId]);

  const handleNoteSubmit = async (values: any) => {
    if (!vendorId) return;
    setSubmittingNote(true);
    try {
      await apiClient.patch(`${API_URL}/vendors/${vendorId}/agreement`, values);
      message.success("Negotiation note added successfully!");
      form.resetFields();
      fetchLogs();
      invalidate({
        resource: "vendors",
        id: vendorId,
        invalidates: ["detail"],
      });
    } catch (error) {
      message.error("Failed to add note");
    } finally {
      setSubmittingNote(false);
    }
  };

  // KPI Calculations
  const fixContracts = fixQuery.data?.data || [];
  const varContracts = varQuery.data?.data || [];
  const oncallContracts = oncallQuery.data?.data || [];
  const allContracts = [...fixContracts, ...varContracts, ...oncallContracts];

  const totalActive = allContracts.length;

  // Total Spend calculation
  const totalSpend = allContracts.reduce((acc, curr: any) => {
    return acc + (Number(curr.distributed_cost) || Number(curr.cost_idr) || 0);
  }, 0);

  // Average Cost (IDR/Unit)
  const avgCost = totalActive > 0 ? totalSpend / totalActive : 0;

  const fixColumns = [
    { title: "SPK Number", dataIndex: "spk_number", key: "spk", render: (v: any) => <Text strong>{v || "-"}</Text> },
    { title: "Mill", dataIndex: ["mill", "name"], key: "mill" },
    { title: "Distributed Cost", dataIndex: "distributed_cost", key: "cost", render: (v: any) => formatIDR(v) },
    { title: "Validity", key: "validity", render: (_: any, r: any) => <Text type="secondary" style={{ fontSize: 13 }}>{formatDate(r.validity_start)} to {formatDate(r.validity_end)}</Text> },
    { title: "Status", dataIndex: "status", key: "status", render: (s: any) => <Tag color={s === 'active' ? 'blue' : 'default'} variant="filled">{s?.toUpperCase()}</Tag> }
  ];

  const oncallColumns = [
    { title: "SPK", dataIndex: "spk_number", key: "spk", render: (v: any) => <Text strong>{v || "-"}</Text> },
    { title: "Route", key: "route", render: (_: any, r: any) => <Text>{r.origin_zone?.name || "-"} <ArrowRightOutlined style={{ fontSize: 10, margin: '0 8px', color: token.colorTextSecondary }} /> {r.dest_zone?.name || "-"}</Text> },
    { title: "MOT/Truck", dataIndex: ["mot", "name"], key: "mot" },
    { title: "Price/Trip", dataIndex: "cost_idr", key: "cost", render: (v: any) => formatIDR(v) },
    { title: "Validity", key: "validity", render: (_: any, r: any) => <Text type="secondary" style={{ fontSize: 13 }}>{formatDate(r.validity_start)} to {formatDate(r.validity_end)}</Text> },
    { title: "Status", dataIndex: "status", key: "status", render: (s: any) => <Tag color={s === 'active' ? 'blue' : 'default'} variant="filled">{s?.toUpperCase()}</Tag> }
  ];

  if (vendorLoading) return <div style={{ height: '80vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Spin size="large" /></div>;

  return (
    <div style={{ padding: '32px 40px', maxWidth: 1400, margin: "0 auto", minHeight: '100vh' }}>
      <div style={{ marginBottom: 16 }}><Breadcrumb /></div>

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Space size="middle">
          <ListButton icon={<ArrowLeftOutlined />} shape="circle" type="text" hideText />
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <Title level={4} style={{ margin: 0, fontWeight: 700 }}>
              {vendor?.name}
            </Title>
            <Text type="secondary" style={{ fontSize: 13 }}>Vendor ID: {vendor?.id} • Code: {vendor?.code}</Text>
          </div>
        </Space>
        <Space>
          <EditButton size="large" style={{ borderRadius: '8px', padding: '0 24px', fontWeight: 600 }} />
        </Space>
      </div>

      <Row gutter={[24, 24]}>
        {/* Profile Card */}
        <Col span={24}>
          <Card styles={{ body: { padding: '24px' } }} style={{ borderRadius: 12, border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary, height: '100%' }}>
            <Descriptions
              title={<span><SolutionOutlined style={{ marginRight: 8, color: token.colorPrimary }} /> Business Information</span>}
              bordered
              size="small"
              column={1}
              styles={{ label: { width: '50%' }, content: { width: '50%' } }}
            >
              <Descriptions.Item label={<span><UserOutlined /> Contact Person</span>}>{vendor?.contact_person || "-"}</Descriptions.Item>
              <Descriptions.Item label={<span><MailOutlined /> Email</span>}>{vendor?.email || "-"}</Descriptions.Item>
              <Descriptions.Item label={<span><PhoneOutlined /> Phone</span>}>{vendor?.phone || "-"}</Descriptions.Item>
              <Descriptions.Item label={<span><EnvironmentOutlined /> Address</span>}>{vendor?.address || "-"}</Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>

        {/* KPI Cards */}
        <Col span={24}>
          <Row gutter={[24, 24]}>
            <Col xs={24} md={8}>
              <Card styles={{ body: { padding: '20px' } }} style={{ height: 110, borderRadius: 12, textAlign: 'center', border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}>
                <Statistic title="Avg Rate per Contract" value={avgCost} formatter={(v) => formatIDR(v)} prefix={<PercentageOutlined style={{ color: token.colorInfo }} />} />
              </Card>
            </Col>
            <Col xs={24} md={8}>
              <Card styles={{ body: { padding: '24px' } }} style={{ height: 110, borderRadius: 12, border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}>
                <Flex justify="space-between" align="center">
                  <div>
                    <Text type="secondary" style={{ fontSize: 13, fontWeight: 600 }}>Total Active Contracts</Text>
                    <Title level={2} style={{ margin: '8px 0 0 0', color: token.colorText }}>{totalActive}</Title>
                  </div>
                  <div style={{ padding: '12px', backgroundColor: token.colorPrimaryBg, borderRadius: '50%' }}>
                    <FileDoneOutlined style={{ fontSize: 24, color: token.colorPrimary }} />
                  </div>
                </Flex>
              </Card>
            </Col>
            <Col xs={24} md={8}>
              <Card styles={{ body: { padding: '24px' } }} style={{ height: 110, borderRadius: 12, border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}>
                <Flex justify="space-between" align="center" style={{ marginBottom: 8 }}>
                  <div>
                    <Text type="secondary" style={{ fontSize: 13, fontWeight: 600 }}>Total Estimated Spend</Text>
                    <Title level={3} style={{ margin: '8px 0 0 0', color: token.colorSuccess }}>{formatIDR(totalSpend)}</Title>
                  </div>
                  <div style={{ padding: '12px', backgroundColor: token.colorSuccessBg, borderRadius: '50%' }}>
                    <DollarOutlined style={{ fontSize: 24, color: token.colorSuccess }} />
                  </div>
                </Flex>
              </Card>
            </Col>
          </Row>
        </Col>

        {/* Tabs Section */}
        <Col span={24}>
          <Card styles={{ body: { padding: '8px 24px 24px 24px' } }} style={{ borderRadius: 12, border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}>
            <Tabs defaultActiveKey="dedicated" items={[
              {
                key: "dedicated",
                label: <span><CarOutlined /> Dedicated Fleet <Tag variant="filled" color="blue" style={{ marginLeft: 8 }}>{fixContracts.length + varContracts.length}</Tag></span>,
                children: (
                  <div style={{ padding: '8px 0' }}>
                    <Title level={5} style={{ marginBottom: 16 }}>Fixed Cost Contracts</Title>
                    <Table rowKey="id" dataSource={fixContracts} columns={fixColumns} pagination={{ pageSize: 5 }} loading={fixQuery.isLoading} size="small" />
                    <Divider style={{ borderColor: token.colorSplit }} />
                    <Title level={5} style={{ marginBottom: 16 }}>Variable Cost Contracts</Title>
                    <Table rowKey="id" dataSource={varContracts} columns={fixColumns} pagination={{ pageSize: 5 }} loading={varQuery.isLoading} size="small" />
                  </div>
                )
              },
              {
                key: "oncall",
                label: <span><NodeIndexOutlined /> Oncall Routes <Tag variant="filled" color="orange" style={{ marginLeft: 8 }}>{oncallContracts.length}</Tag></span>,
                children: (
                  <div style={{ padding: '8px 0' }}>
                    <Table rowKey="id" dataSource={oncallContracts} columns={oncallColumns} pagination={{ pageSize: 10 }} loading={oncallQuery.isLoading} size="small" />
                  </div>
                )
              },
              {
                key: "negotiation",
                label: <span><HistoryOutlined /> Negotiation Tracker</span>,
                children: (
                  <Row gutter={[24, 24]} style={{ marginTop: 16 }}>
                    <Col xs={24} md={10}>
                      <div style={{ backgroundColor: token.colorFillAlter, padding: 20, borderRadius: 8, border: `1px solid ${token.colorBorderSecondary}` }}>
                        <Title level={5} style={{ marginTop: 0 }}>Add Negotiation Note</Title>
                        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>Log a new agreement or meeting result for this vendor.</Text>
                        <Form form={form} layout="vertical" onFinish={handleNoteSubmit}>
                          <Form.Item name="changed_by" label="Negotiator Name" rules={[{ required: true }]}>
                            <Input placeholder="e.g. Procurement Team" />
                          </Form.Item>
                          <Form.Item name="note" label="Agreement Details" rules={[{ required: true }]}>
                            <Input.TextArea rows={4} placeholder="Summarize the negotiation result..." />
                          </Form.Item>
                          <Button block type="primary" htmlType="submit" loading={submittingNote}>Save Negotiation Trace</Button>
                        </Form>
                      </div>
                    </Col>
                    <Col xs={24} md={14}>
                      <Title level={5} style={{ marginTop: 0 }}>Timeline</Title>
                      {logsLoading ? <Spin /> : (auditLogs?.length ?? 0) === 0 ? <Empty /> : (
                        <Timeline
                          mode="left"
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
                                    <Text>{log.agreement_note}</Text>
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
