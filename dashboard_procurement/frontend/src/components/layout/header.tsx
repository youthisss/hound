"use client";

import React from "react";
import { Layout, Button, Input, Space, Typography } from "antd";
import { BellOutlined, SearchOutlined, SunOutlined, MoonOutlined, MenuFoldOutlined, MenuUnfoldOutlined } from "@ant-design/icons";
import { useContext, useEffect, useState } from "react";
import { ColorModeContext } from "@/contexts/color-mode";
import dayjs from "dayjs";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

const { Header: AntdHeader } = Layout;

export const Header = ({ collapsed, setCollapsed }: { collapsed: boolean, setCollapsed: (val: boolean) => void }) => {
  const { mode, setMode } = useContext(ColorModeContext);
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();

  const isSearchablePage = ["/vendors", "/mills", "/contracts/dedicated-fix", "/contracts/dedicated-var", "/contracts/oncall"].includes(pathname);
  const query = searchParams.get("q") || "";
  const [searchValue, setSearchValue] = useState(query);

  useEffect(() => {
    setSearchValue(query);
  }, [query, pathname]);

  const pushSearch = (value: string) => {
    if (!isSearchablePage) return;
    const params = new URLSearchParams(searchParams.toString());
    if (value.trim()) {
      params.set("q", value.trim());
    } else {
      params.delete("q");
    }
    router.push(`${pathname}${params.toString() ? `?${params.toString()}` : ""}`);
  };

  return (
    <AntdHeader
      style={{
        backgroundColor: "var(--ant-color-bg-container)",
        borderBottom: "1px solid var(--ant-color-border)",
        display: "flex",
        justifyContent: "flex-end",
        alignItems: "center",
        padding: "0 24px",
        height: "64px",
        position: "sticky",
        top: 0,
        zIndex: 998,
      }}
      >
      <Button 
        type="text" 
        icon={collapsed ? <MenuUnfoldOutlined style={{ fontSize: '18px' }} /> : <MenuFoldOutlined style={{ fontSize: '18px' }} />} 
        onClick={() => setCollapsed(!collapsed)} 
        style={{ marginRight: 16 }}
      />
      <div style={{ flex: 1, display: "flex", alignItems: "center" }}>
        <Input 
          prefix={<SearchOutlined style={{ color: 'var(--ant-color-text-secondary)', marginRight: 8 }} />}
          placeholder={isSearchablePage ? "Search contracts, vendors, or mills..." : "Search is available on list pages"} 
          allowClear
          style={{ maxWidth: 400, borderRadius: '8px' }}
          value={searchValue}
          disabled={!isSearchablePage}
          onPressEnter={() => pushSearch(searchValue)}
          onChange={(e) => {
            setSearchValue(e.target.value);
            if (e.target.value === "") {
              pushSearch("");
            }
          }}
        />
      </div>

      <Space size="middle" style={{ alignItems: "center" }}>
        <Typography.Text type="secondary" strong style={{ fontSize: "13px" }}>
          {dayjs().format("dddd, DD MMM YYYY")}
        </Typography.Text>

        <Button
          type="text"
          icon={mode === "light" ? <MoonOutlined style={{ fontSize: '18px' }} /> : <SunOutlined style={{ fontSize: '18px' }} />}
          onClick={() => setMode(mode === "light" ? "dark" : "light")}
        />
        
        <Button type="text" icon={<BellOutlined style={{ fontSize: '18px' }} />} />
      </Space>
    </AntdHeader>
  );
};
