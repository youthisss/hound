"use client";

import React from "react";
import { Layout, Menu, Typography, Button } from "antd";
import { usePathname, useRouter } from "next/navigation";
import {
  DashboardOutlined,
  CloudUploadOutlined,
  ShopOutlined,
  EnvironmentOutlined,
  FileDoneOutlined,
  CarOutlined,
  LogoutOutlined,
  NodeIndexOutlined,
} from "@ant-design/icons";
import { clearAuth, getAuthUser } from "@/lib/auth";

const { Sider } = Layout;
const { Text } = Typography;

export const CustomSider = ({ collapsed, onCollapse }: { collapsed: boolean, onCollapse: (val: boolean) => void }) => {
  const pathname = usePathname();
  const router = useRouter();
  const authUser = getAuthUser();

  const menuItems = [
    {
      key: "/overview",
      icon: <DashboardOutlined style={{ fontSize: '18px' }} />,
      label: "Overview",
    },
    {
      key: "master",
      label: "Master Data",
      type: "group" as const,
      children: [
        { key: "/vendors", icon: <ShopOutlined style={{ fontSize: '18px' }} />, label: "Vendors" },
        { key: "/mills", icon: <EnvironmentOutlined style={{ fontSize: '18px' }} />, label: "Mills" },
      ]
    },
    {
      key: "contracts",
      label: "Contracts",
      type: "group" as const,
      children: [
        { key: "/contracts/dedicated-fix", icon: <FileDoneOutlined style={{ fontSize: '18px' }} />, label: "Dedicated Fix" },
        { key: "/contracts/dedicated-var", icon: <NodeIndexOutlined style={{ fontSize: '18px' }} />, label: "Dedicated Var" },
        { key: "/contracts/oncall", icon: <CarOutlined style={{ fontSize: '18px' }} />, label: "Oncall Routing" },
      ]
    },
    {
      key: "/import",
      icon: <CloudUploadOutlined style={{ fontSize: '18px' }} />,
      label: "Import Wizard",
    },
  ];

  return (
    <>
      <style>{`
        .custom-menu .ant-menu-item-group-title {
          transition: all 0.2s;
        }
        ${collapsed ? `
        .custom-menu .ant-menu-item-group-title {
          padding: 0 !important;
          height: 0 !important;
          opacity: 0 !important;
          margin: 0 !important;
          overflow: hidden !important;
        }
        ` : ''}
      `}</style>
      <Sider
        collapsible
      collapsed={collapsed}
      trigger={null}
      width={260}
      collapsedWidth={80}
      style={{
        borderRight: "1px solid var(--ant-color-border)",
        backgroundColor: "var(--ant-color-bg-container)",
        height: "100vh",
        position: "fixed",
        left: 0,
        top: 0,
        bottom: 0,
        zIndex: 999,
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
        <div style={{ 
          padding: collapsed ? "24px 0" : "24px", 
          display: "flex", 
          alignItems: "center", 
          justifyContent: "center", 
          gap: collapsed ? 0 : "12px", 
          height: "80px", 
          flexShrink: 0,
          transition: "all 0.2s"
        }}>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--ant-color-text)", flexShrink: 0 }}>
            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
            <polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline>
            <line x1="12" y1="22.08" x2="12" y2="12"></line>
          </svg>
          <span style={{ 
            display: "inline-block",
            fontSize: "20px", fontWeight: 700, color: "var(--ant-color-text)", 
            whiteSpace: "nowrap", opacity: collapsed ? 0 : 1, width: collapsed ? 0 : 130, 
            overflow: "hidden", transition: "all 0.2s" 
          }}>
            Procurement
          </span>
        </div>

      <div style={{ flex: 1, padding: "0 12px", overflowY: "auto", overflowX: "hidden" }}>
        <Menu
          className="custom-menu"
          mode="inline"
          selectedKeys={[pathname]}
          onClick={({ key }) => router.push(key)}
          style={{ borderRight: "none", fontSize: "14px", fontWeight: 500 }}
          items={menuItems.map(item => {
            if (item.type === "group" && item.children) {
              return {
                ...item,
                label: collapsed ? null : item.label,
                style: { marginTop: collapsed ? 0 : '16px', color: 'var(--ant-color-text-secondary)', fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.5px' },
                children: item.children.map(child => ({
                  ...child,
                  style: {
                    borderRadius: "8px",
                    marginBottom: "4px",
                    fontWeight: pathname === child.key ? 600 : 500,
                    backgroundColor: pathname === child.key ? "rgba(255,255,255,0.08)" : "transparent",
                    color: pathname === child.key ? "var(--ant-color-text)" : "var(--ant-color-text-secondary)",
                  }
                }))
              }
            }
            return {
              ...item,
              style: {
                borderRadius: "8px",
                marginBottom: "4px",
                fontWeight: pathname === item.key ? 600 : 500,
                backgroundColor: pathname === item.key ? "rgba(255,255,255,0.08)" : "transparent",
                color: pathname === item.key ? "var(--ant-color-text)" : "var(--ant-color-text-secondary)",
              }
            }
          })}
        />
      </div>

        <div style={{ padding: collapsed ? "20px 0" : "20px", display: "flex", justifyContent: "center", borderTop: "1px solid var(--ant-color-border)", flexShrink: 0 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: "12px", width: "100%", alignItems: collapsed ? "center" : "stretch" }}>
            <div style={{ 
              opacity: collapsed ? 0 : 1, 
              height: collapsed ? 0 : 'auto', 
              overflow: "hidden", 
              transition: "all 0.2s",
              whiteSpace: "nowrap"
            }}>
              <Text style={{ display: "block", fontWeight: 600 }}>Administrator</Text>
              <Text type="secondary" style={{ fontSize: "13px" }}>{authUser?.username || "admin"}</Text>
            </div>
            
            <Button 
              type="text" 
              icon={<LogoutOutlined style={{ fontSize: '18px', color: '#ef4444' }} />} 
              title="Logout"
              onClick={() => {
                clearAuth();
                router.push("/login");
              }}
              style={{ 
                width: collapsed ? "40px" : "100%", 
                height: collapsed ? "40px" : undefined,
                padding: collapsed ? 0 : "4px 15px",
                textAlign: collapsed ? "center" : "left", 
                justifyContent: collapsed ? "center" : "flex-start",
                background: "transparent",
                color: "#ef4444",
                borderRadius: "8px",
                fontWeight: 500,
                transition: "all 0.2s"
              }}
            >
              <span style={{ 
                display: "inline-block",
                opacity: collapsed ? 0 : 1, 
                width: collapsed ? 0 : 'auto', 
                overflow: 'hidden', 
                transition: "all 0.2s", 
                marginLeft: collapsed ? 0 : 8 
              }}>
                Logout
              </span>
            </Button>
          </div>
        </div>
      </div>
    </Sider>
    </>
  );
};
