"use client";

import React, { useState } from "react";
import { Layout, theme } from "antd";
import { CustomSider } from "./sider";
import { Header } from "./header";

const { Content } = Layout;

export const CustomLayout = ({ children }: { children: React.ReactNode }) => {
  const [collapsed, setCollapsed] = useState(false);
  const { token } = theme.useToken();

  return (
    <Layout style={{ minHeight: "100vh", backgroundColor: token.colorBgLayout }}>
      <CustomSider collapsed={collapsed} onCollapse={setCollapsed} />
      <Layout style={{ marginLeft: collapsed ? 80 : 260, transition: 'margin-left 0.2s', backgroundColor: token.colorBgLayout }}>
        <Header collapsed={collapsed} setCollapsed={setCollapsed} />
        <Content>
          {children}
        </Content>
      </Layout>
    </Layout>
  );
};

