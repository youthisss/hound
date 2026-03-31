"use client";

import { useState } from "react";
import { App, Button, Card, Form, Input, Space, Typography, theme, Grid, Flex, Divider } from "antd";
import {
  LockOutlined,
  UserOutlined,
  BarChartOutlined,
  SafetyCertificateOutlined,
  FileDoneOutlined,
  LoginOutlined,
} from "@ant-design/icons";
import axios from "axios";
import { useRouter } from "next/navigation";
import { setAuth } from "@/lib/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080/api/v1";
const { Title, Text } = Typography;

type LoginResponse = {
  access_token: string;
  token_type: string;
  user: {
    id: number;
    name: string;
    username: string;
  };
};

function ProcurementLogo({ size = 24 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ color: "var(--ant-color-text)", flexShrink: 0 }}
    >
      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
      <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
      <line x1="12" y1="22.08" x2="12" y2="12" />
    </svg>
  );
}

export default function LoginPage() {
  const { token } = theme.useToken();
  const screens = Grid.useBreakpoint();
  const isDesktop = !!screens.lg;

  const [loading, setLoading] = useState(false);
  const { message } = App.useApp();
  const router = useRouter();

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      const { data } = await axios.post<LoginResponse>(`${API_URL}/auth/login`, values);
      setAuth(data.access_token, data.user);
      message.success("Login successful");
      router.replace("/overview");
    } catch (error: any) {
      const err = error?.response?.data?.error || "Invalid credentials";
      message.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: isDesktop ? 32 : 16,
        position: "relative",
        overflow: "hidden",
        backgroundColor: token.colorBgLayout,
      }}
    >
      <div
        style={{
          position: "absolute",
          width: "50vw",
          height: "50vw",
          borderRadius: "50%",
          filter: "blur(120px)",
          opacity: 0.16,
          background: token.colorFillSecondary,
          top: "-10%",
          left: "-10%",
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          width: "40vw",
          height: "40vw",
          borderRadius: "50%",
          filter: "blur(120px)",
          opacity: 0.12,
          background: token.colorFillTertiary,
          bottom: "-10%",
          right: "-10%",
          pointerEvents: "none",
        }}
      />

      <Card
        variant="borderless"
        styles={{ body: { padding: 0 } }}
        style={{
          width: "100%",
          maxWidth: isDesktop ? 1000 : 440,
          borderRadius: 24,
          border: `1px solid ${token.colorBorderSecondary}`,
          boxShadow: token.boxShadow,
          overflow: "hidden",
          background: "transparent",
          position: "relative",
          zIndex: 1,
        }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: isDesktop ? "1fr 1.1fr" : "1fr",
            minHeight: isDesktop ? 600 : "auto",
          }}
        >
          {isDesktop && (
            <div
              style={{
                padding: "48px 40px",
                backgroundColor: token.colorFillAlter,
                borderRight: `1px solid ${token.colorSplit}`,
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
              }}
            >
              <div>
                <Space align="center" style={{ marginBottom: 32 }}>
                  <ProcurementLogo size={24} />
                  <Text strong style={{ fontSize: 18, letterSpacing: 0.5 }}>
                    APP PROCUREMENT
                  </Text>
                </Space>

                <Title level={2} style={{ margin: "0 0 16px 0", lineHeight: 1.25, fontWeight: 700 }}>
                  Strategic <br />
                  <span style={{ color: token.colorText }}>Logistics Procurement</span>
                </Title>
                <Text type="secondary" style={{ fontSize: 15, lineHeight: 1.6, display: "block" }}>
                  A centralized workspace to monitor vendor performance, cost efficiency, and logistics contract status in real time.
                </Text>
              </div>

              <div>
                <Divider style={{ borderColor: token.colorBorderSecondary, margin: "32px 0" }} />
                <Space orientation="vertical" size={20} style={{ width: "100%" }}>
                  <Flex align="flex-start" gap={12}>
                    <div
                      style={{
                        padding: 8,
                        backgroundColor: token.colorBgContainer,
                        borderRadius: 8,
                        border: `1px solid ${token.colorBorderSecondary}`,
                      }}
                    >
                      <BarChartOutlined style={{ color: token.colorTextSecondary, fontSize: 16 }} />
                    </div>
                    <div>
                      <Text strong style={{ display: "block", marginBottom: 2 }}>
                        Cost Efficiency Analytics
                      </Text>
                      <Text type="secondary" style={{ fontSize: 13 }}>
                        Benchmark on-call rates against dedicated fleet costs.
                      </Text>
                    </div>
                  </Flex>
                  <Flex align="flex-start" gap={12}>
                    <div
                      style={{
                        padding: 8,
                        backgroundColor: token.colorBgContainer,
                        borderRadius: 8,
                        border: `1px solid ${token.colorBorderSecondary}`,
                      }}
                    >
                      <FileDoneOutlined style={{ color: token.colorTextSecondary, fontSize: 16 }} />
                    </div>
                    <div>
                      <Text strong style={{ display: "block", marginBottom: 2 }}>
                        Vendor 360-degree View
                      </Text>
                      <Text type="secondary" style={{ fontSize: 13 }}>
                        Track negotiation history and partner SLA compliance.
                      </Text>
                    </div>
                  </Flex>
                </Space>
              </div>
            </div>
          )}

          <div
            style={{
              padding: isDesktop ? "64px 48px" : "40px 24px",
              backgroundColor: token.colorBgContainer,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center",
            }}
          >
            <div style={{ maxWidth: 360, width: "100%", margin: "0 auto" }}>
              {!isDesktop && (
                <Space align="center" style={{ marginBottom: 32 }}>
                  <ProcurementLogo size={22} />
                  <Text strong style={{ fontSize: 16, letterSpacing: 0.5 }}>
                    Procurement
                  </Text>
                </Space>
              )}

              <Space orientation="vertical" size={4} style={{ marginBottom: 36, width: "100%" }}>
                <Title level={3} style={{ margin: 0, fontWeight: 700 }}>
                  Welcome back
                </Title>
                <Text type="secondary" style={{ fontSize: 15 }}>
                  Enter your credentials to access your workspace.
                </Text>
              </Space>

              <Form layout="vertical" onFinish={onFinish} autoComplete="off" requiredMark={false}>
                <Form.Item
                  label={<Text strong>Username</Text>}
                  name="username"
                  rules={[{ required: true, message: "Please enter your username" }]}
                >
                  <Input
                    prefix={<UserOutlined style={{ color: token.colorTextTertiary, marginRight: 4 }} />}
                    placeholder="Enter your username"
                    size="large"
                    style={{ padding: "10px 14px", borderRadius: 8 }}
                  />
                </Form.Item>

                <Form.Item
                  label={<Text strong>Password</Text>}
                  name="password"
                  rules={[{ required: true, message: "Please enter your password" }]}
                  style={{ marginBottom: 32 }}
                >
                  <Input.Password
                    prefix={<LockOutlined style={{ color: token.colorTextTertiary, marginRight: 4 }} />}
                    placeholder="Enter your password"
                    size="large"
                    style={{ padding: "10px 14px", borderRadius: 8 }}
                  />
                </Form.Item>

                <Button
                  type="primary"
                  htmlType="submit"
                  block
                  size="large"
                  loading={loading}
                  icon={!loading && <LoginOutlined />}
                  style={{ height: 48, borderRadius: 8, fontSize: 15, fontWeight: 600 }}
                >
                  Sign In to Dashboard
                </Button>
              </Form>

              <div style={{ marginTop: 32, textAlign: "center" }}>
                <Text type="secondary" style={{ fontSize: 13 }}>
                  <SafetyCertificateOutlined style={{ marginRight: 6 }} />
                  Secure access for authorized personnel only.
                </Text>
              </div>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
