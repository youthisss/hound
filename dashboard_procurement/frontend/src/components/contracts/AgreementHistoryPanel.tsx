"use client";

import { Form, Input, Button, Timeline, Typography, Divider, Spin, App, Card } from "antd";
import { useEffect, useState } from "react";
import dayjs from "dayjs";
import { useInvalidate } from "@refinedev/core";
import { apiClient } from "@/lib/api-client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080/api/v1";

const { Text, Title } = Typography;

interface AuditLog {
  id: number;
  entity_type: string;
  entity_id: number;
  action: string;
  changed_by: string;
  agreement_note: string;
  created_at: string;
}

interface Props {
  contractId?: number;
  resourceSuffix: string; 
  entityTypeDb: string; 
}

export default function AgreementHistoryPanel({ contractId, resourceSuffix, entityTypeDb }: Props) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const { message } = App.useApp();
  const invalidate = useInvalidate();

  useEffect(() => {
    if (contractId) {
      fetchHistory();
    }
  }, [contractId]);

  const fetchHistory = async () => {
    if (!contractId) return;
    setHistoryLoading(true);
    try {
      const { data } = await apiClient.get(`${API_URL}/audit/${entityTypeDb}/${contractId}`);
      setLogs(data);
    } catch (error) {
      console.error(error);
      message.error("Failed to load audit history");
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleSubmit = async (values: any) => {
    if (!contractId) return;
    setLoading(true);
    try {
      const { changed_by, note } = values;
      await apiClient.patch(`${API_URL}/contracts/${resourceSuffix}/${contractId}/agreement`, {
        changed_by,
        note
      });
      
      message.success("Agreement updated successfully! History saved.");
      form.resetFields();
      fetchHistory(); // Refresh the list
      invalidate({
        resource: `contracts/${resourceSuffix}`,
        invalidates: ["list", "detail"],
      });
    } catch (error) {
      console.error(error);
      message.error("Failed to update agreement");
    } finally {
      setLoading(false);
    }
  };

  if (!contractId) return <Card loading />;

  return (
    <Card title="Agreement Updates & History" variant="borderless">
      <Text type="secondary" style={{ display: "block", marginBottom: 16 }}>
        Submit a new agreement note. This will append a log to the historical tracker.
      </Text>

      <Form form={form} layout="vertical" onFinish={handleSubmit}>
        <Form.Item
          name="changed_by"
          label="Updated By (Name)"
          rules={[{ required: true, message: "Please input your name" }]}
        >
          <Input placeholder="John Doe" />
        </Form.Item>
        <Form.Item
          name="note"
          label="Agreement Note/Details"
          rules={[{ required: true, message: "Please input the agreement details" }]}
        >
          <Input.TextArea rows={3} placeholder="e.g., Vendor agreed to reduce cost by 5%." />
        </Form.Item>
        <Form.Item style={{ textAlign: "right" }}>
          <Button type="primary" htmlType="submit" loading={loading}>Save Note</Button>
        </Form.Item>
      </Form>

      <Divider />

      <Title level={5}>Timeline</Title>
      {historyLoading ? (
        <div style={{ textAlign: "center", padding: 20 }}><Spin /></div>
      ) : logs.length === 0 ? (
        <Text type="secondary">No history found for this contract.</Text>
      ) : (
        <Timeline
          style={{ marginTop: 16 }}
          items={logs.sort((a,b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()).map(log => ({
            key: log.id,
            color: log.action === 'create' ? 'green' : 'blue',
            children: (
              <>
                <div style={{ marginBottom: 4 }}>
                  <Text strong>{log.action.toUpperCase()}</Text> by <Text mark>{log.changed_by || "System"}</Text>
                  <div style={{ fontSize: 12, color: 'gray' }}>
                    {dayjs(log.created_at).format('DD MMM YYYY, HH:mm')}
                  </div>
                </div>
                {log.agreement_note && (
                  <div style={{ background: 'rgba(255,255,255,0.04)', padding: '8px 12px', borderRadius: 4, marginTop: 4, border: '1px solid rgba(255,255,255,0.1)' }}>
                    <Text italic>"{log.agreement_note}"</Text>
                  </div>
                )}
              </>
            ),
          }))}
        />
      )}
    </Card>
  );
}
