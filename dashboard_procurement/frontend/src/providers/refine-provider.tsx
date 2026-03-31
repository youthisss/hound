"use client";

import { Refine } from "@refinedev/core";
import { RefineKbar, RefineKbarProvider } from "@refinedev/kbar";
import { useNotificationProvider } from "@refinedev/antd";
import "@refinedev/antd/dist/reset.css";
import { App as AntdApp, Spin } from "antd";
import { ColorModeContextProvider } from "@/contexts/color-mode";
import routerProvider from "@refinedev/nextjs-router";
import React, { useEffect, useMemo, useState } from "react";
import dataProvider from "@refinedev/simple-rest";
import { usePathname, useRouter } from "next/navigation";

import { CustomLayout } from "@/components/layout";
import { clearAuth, getToken } from "@/lib/auth";
import { apiClient } from "@/lib/api-client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080/api/v1";

export default function RefineProvider({ children }: { children: React.ReactNode }) {
  const antdNotificationProvider = useNotificationProvider();
  const pathname = usePathname();
  const router = useRouter();
  const [checkingAuth, setCheckingAuth] = useState(true);
  const isLoginPage = pathname === "/login";

  useEffect(() => {
    const token = getToken();
    if (!token && !isLoginPage) {
      router.replace("/login");
      return;
    }
    if (token && isLoginPage) {
      router.replace("/overview");
      return;
    }
    setCheckingAuth(false);
  }, [isLoginPage, router]);

  const authProvider = useMemo(
    () => ({
      login: async () => ({ success: true }),
      logout: async () => {
        clearAuth();
        return { success: true, redirectTo: "/login" };
      },
      check: async () => {
        const token = getToken();
        if (token) {
          return { authenticated: true };
        }
        return { authenticated: false, redirectTo: "/login", logout: true };
      },
      getPermissions: async () => null,
      getIdentity: async () => null,
      onError: async () => ({ error: undefined }),
    }),
    [],
  );
  
  const customNotificationProvider = {
    ...antdNotificationProvider,
    open: (params: any) => {
      antdNotificationProvider.open({
        ...params,
        title: params.message, // Map 'message' to 'title' for AntD v6
      });
    },
  };

  if (checkingAuth) {
    return (
      <div style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <ColorModeContextProvider>
      <AntdApp>
        <RefineKbarProvider>
          <Refine
            dataProvider={dataProvider(API_URL, apiClient)}
            authProvider={authProvider}
            notificationProvider={customNotificationProvider}
            routerProvider={routerProvider}
            resources={[
              {
                name: "overview",
                list: "/overview",
                meta: {
                  label: "Overview",
                  icon: "DashboardOutlined",
                },
              },
              {
                name: "import",
                list: "/import",
                meta: {
                  label: "Import Wizard",
                },
              },
              {
                name: "vendors",
                list: "/vendors",
                create: "/vendors/create",
                edit: "/vendors/edit/:id",
                show: "/vendors/show/:id",
                meta: {
                  label: "Vendors",
                  parent: "masterData",
                },
              },
              {
                name: "mills",
                list: "/mills",
                create: "/mills/create",
                edit: "/mills/edit/:id",
                show: "/mills/show/:id",
                meta: {
                  label: "Mills",
                  parent: "masterData",
                },
              },
              {
                name: "contracts/dedicated-fix",
                list: "/contracts/dedicated-fix",
                create: "/contracts/dedicated-fix/create",
                edit: "/contracts/dedicated-fix/edit/:id",
                meta: {
                  label: "Dedicated Fix",
                  parent: "contracts",
                },
              },
              {
                name: "contracts/dedicated-var",
                list: "/contracts/dedicated-var",
                create: "/contracts/dedicated-var/create",
                edit: "/contracts/dedicated-var/edit/:id",
                meta: {
                  label: "Dedicated Var",
                  parent: "contracts",
                },
              },
              {
                name: "contracts/oncall",
                list: "/contracts/oncall",
                create: "/contracts/oncall/create",
                edit: "/contracts/oncall/edit/:id",
                meta: {
                  label: "Oncall Routing",
                  parent: "contracts",
                },
              },
            ]}
            options={{
              syncWithLocation: true,
              warnWhenUnsavedChanges: true,
              projectId: "rygell-procurement",
            }}
          >
            {isLoginPage ? children : <CustomLayout>{children}</CustomLayout>}
            <RefineKbar />
          </Refine>
        </RefineKbarProvider>
      </AntdApp>
    </ColorModeContextProvider>
  );
}
