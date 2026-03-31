"use client";

import { RefineThemes } from "@refinedev/antd";
import { ConfigProvider, theme } from "antd";
import React, { createContext, PropsWithChildren, useEffect, useState } from "react";

type ColorModeContextType = {
  mode: string;
  setMode: (mode: string) => void;
};

export const ColorModeContext = createContext<ColorModeContextType>({} as ColorModeContextType);

export const ColorModeContextProvider: React.FC<PropsWithChildren> = ({ children }) => {
  const [isMounted, setIsMounted] = useState(false);
  const [mode, setMode] = useState("dark");

  useEffect(() => {
    setIsMounted(true);
    const storedTheme = window.localStorage.getItem("colorMode");
    if (storedTheme) {
      setMode(storedTheme);
    }
  }, []);

  useEffect(() => {
    if (isMounted) {
      window.localStorage.setItem("colorMode", mode);
    }
  }, [mode, isMounted]);

  const setColorMode = () => {
    if (mode === "light") {
      setMode("dark");
    } else {
      setMode("light");
    }
  };

  if (!isMounted) {
    return null;
  }

  return (
    <ColorModeContext.Provider
      value={{
        setMode: setColorMode,
        mode,
      }}
    >
      <ConfigProvider
        theme={{
          algorithm: mode === "light" ? theme.defaultAlgorithm : theme.darkAlgorithm,
          token: {
            colorPrimary: "#1677ff", // Blue for neutral/default hover actions
            colorInfo: "#1677ff",
            fontFamily: "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
            borderRadius: 8,
            boxShadow: mode === "light" ? '0 1px 3px 0 rgba(0, 0, 0, 0.04)' : 'none',
            boxShadowSecondary: mode === "light" ? '0 4px 6px -1px rgba(0, 0, 0, 0.05)' : 'none',
            boxShadowTertiary: mode === "light" ? '0 10px 15px -3px rgba(0, 0, 0, 0.05)' : 'none',
            colorBorder: mode === "dark" ? "#000000" : "#e5e7eb", // Soft gray border in light mode
            colorBorderSecondary: mode === "dark" ? "#000000" : "#f3f4f6",
            colorBgLayout: mode === "dark" ? "#000000" : "#f8fafc", // Explicit dark/light layout backgrounds
          },
          components: {
            Menu: {
              itemActiveBg: mode === "dark" ? "rgba(22, 119, 255, 0.15)" : "#e6f4ff",
              itemSelectedBg: mode === "dark" ? "rgba(22, 119, 255, 0.15)" : "#e6f4ff",
              itemSelectedColor: mode === "dark" ? "#69b1ff" : "#1677ff",
            },
            Button: {
              defaultShadow: 'none',
              primaryShadow: 'none',
            }
          },
        }}
      >
        {children}
      </ConfigProvider>
    </ColorModeContext.Provider>
  );
};
