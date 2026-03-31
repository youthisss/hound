"use client";

import { useState, useEffect, useMemo } from "react";
import { useNavigation } from "@refinedev/core";
import { Card, Typography, Row, Col, Button, Spin, Tag, Flex, Progress, List, Space, Segmented, theme } from "antd";
import {
  DownloadOutlined,
  DollarOutlined,
  ThunderboltOutlined,
  AlertOutlined,
  CheckCircleOutlined,
  PieChartOutlined,
  BarChartOutlined,
  ClockCircleOutlined,
  HistoryOutlined,
  RightOutlined,
  TrophyOutlined
} from "@ant-design/icons";
import {
  PieChart, Pie, Cell, Tooltip as RechartsTooltip, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Legend
} from 'recharts';
import { getToken } from "@/lib/auth";

const { Title, Text } = Typography;
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080/api/v1";

const formatIDR = (val: number) => {
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(val);
};

const formatNumber = (val: number) => {
  return new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(val);
};

const formatDate = (dateStr: string | null | undefined) => {
  if (!dateStr || dateStr === "-") return "-";
  const dateOnly = dateStr.split('T')[0];
  const [year, month, day] = dateOnly.split('-');
  if (!year || !month || !day) return dateStr;
  return `${day}/${month}/${year}`;
};

// Colors for charts (These remain static hex as they represent data visualization lines/bars)
const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316'];

export default function DashboardOverview() {
  const { token } = theme.useToken();
  const { edit } = useNavigation();

  const [loading, setLoading] = useState(true);
  const [fixContracts, setFixContracts] = useState<any[]>([]);
  const [varContracts, setVarContracts] = useState<any[]>([]);
  const [oncallContracts, setOncallContracts] = useState<any[]>([]);
  const [mills, setMills] = useState<any[]>([]);
  const [vendors, setVendors] = useState<any[]>([]);
  const [mots, setMots] = useState<any[]>([]);

  // State for interactive charts
  const [analyticView, setAnalyticView] = useState<'Vendor' | 'Mill'>('Vendor');

  useEffect(() => {
    const fetchData = async () => {
      try {
        const token = getToken();
        const headers = token ? { Authorization: `Bearer ${token}` } : undefined;
        const [fRes, vRes, oRes, mRes, venRes, motRes] = await Promise.all([
          fetch(`${API_URL}/contracts/dedicated-fix?_start=0&_end=9999`, { headers }).then(r => r.json().catch(() => [])),
          fetch(`${API_URL}/contracts/dedicated-var?_start=0&_end=9999`, { headers }).then(r => r.json().catch(() => [])),
          fetch(`${API_URL}/contracts/oncall?_start=0&_end=9999`, { headers }).then(r => r.json().catch(() => [])),
          fetch(`${API_URL}/mills?_start=0&_end=9999`, { headers }).then(r => r.json().catch(() => [])),
          fetch(`${API_URL}/vendors?_start=0&_end=9999`, { headers }).then(r => r.json().catch(() => [])),
          fetch(`${API_URL}/mots?_start=0&_end=9999`, { headers }).then(r => r.json().catch(() => [])),
        ]);

        setFixContracts(Array.isArray(fRes) ? fRes : []);
        setVarContracts(Array.isArray(vRes) ? vRes : []);
        setOncallContracts(Array.isArray(oRes) ? oRes : []);
        setMills(Array.isArray(mRes) ? mRes : []);
        setVendors(Array.isArray(venRes) ? venRes : []);
        setMots(Array.isArray(motRes) ? motRes : []);
      } catch (error) {
        console.error("Failed to fetch dashboard data:", error);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  // --- KPI Aggregations ---

  const totalLandedCost = useMemo(() => {
    let sum = 0;
    fixContracts.forEach(c => sum += Number(c.distributed_cost) || 0);
    varContracts.forEach(c => sum += Number(c.cost_idr) || 0);
    oncallContracts.forEach(c => sum += Number(c.cost_idr) || 0);
    return sum;
  }, [fixContracts, varContracts, oncallContracts]);

  const avgRunningCost = useMemo(() => {
    let sum = 0;
    let count = 0;
    oncallContracts.forEach(c => {
      const val = Number(c.running_cost_idr) || 0;
      if (val > 0) {
        sum += val;
        count++;
      }
    });
    return count > 0 ? formatNumber(sum / count) : '0';
  }, [varContracts, oncallContracts]);

  const expiringContracts = useMemo(() => {
    const now = new Date();
    const thirtyDaysMs = 30 * 24 * 60 * 60 * 1000;

    const checkExpiry = (contract: any, type: string) => {
      if (!contract.validity_end) return null;
      const end = new Date(contract.validity_end);
      const diff = end.getTime() - now.getTime();
      if (diff > 0 && diff < thirtyDaysMs) {
        return { ...contract, type, daysLeft: Math.ceil(diff / (1000 * 60 * 60 * 24)) };
      }
      return null;
    };

    const expiring = [
      ...fixContracts.map(c => checkExpiry(c, 'Fix')),
      ...varContracts.map(c => checkExpiry(c, 'Var')),
      ...oncallContracts.map(c => checkExpiry(c, 'Oncall'))
    ].filter(Boolean);

    return expiring;
  }, [fixContracts, varContracts, oncallContracts]);

  const taskProgress = fixContracts.length + varContracts.length + oncallContracts.length > 0 ? 100 : 0;

  // --- Chart Data Processing ---

  // 1. Contract Proportion (Fix vs Var vs Oncall)
  const contractPropData = useMemo(() => {
    return [
      { name: 'Dedicated Fix', value: fixContracts.length },
      { name: 'Dedicated Var', value: varContracts.length },
      { name: 'Oncall Spot', value: oncallContracts.length },
    ];
  }, [fixContracts, varContracts, oncallContracts]);

  // 2. Trend Data (Memastikan seluruh 12 bulan selalu ada di X-Axis)
  const trendData = useMemo(() => {
    const monthsOrder = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const monthCounts: Record<string, { dedicated: number, oncall: number }> = {};

    // Inisialisasi semua bulan dengan nilai 0 agar X-Axis tidak terpotong
    monthsOrder.forEach(m => {
      monthCounts[m] = { dedicated: 0, oncall: 0 };
    });

    const processMonth = (c: any, type: 'dedicated' | 'oncall') => {
      const dateVal = c.validity_start || c.created_at;
      if (!dateVal) return;
      const monthStr = new Date(dateVal).toLocaleString('en-US', { month: 'short' });
      const cost = Number(c.distributed_cost || c.cost_idr) || 0;

      if (monthCounts[monthStr]) {
        monthCounts[monthStr][type] += cost;
      }
    };

    fixContracts.forEach(c => processMonth(c, 'dedicated'));
    varContracts.forEach(c => processMonth(c, 'dedicated'));
    oncallContracts.forEach(c => processMonth(c, 'oncall'));

    // Map kembali ke bentuk array berurutan sesuai monthsOrder
    return monthsOrder.map(m => ({
      month: m,
      dedicated: monthCounts[m].dedicated,
      oncall: monthCounts[m].oncall
    }));
  }, [fixContracts, varContracts, oncallContracts]);

  // 3. Analytics Data (Sorted by Vendor or Mill)
  const sortedAnalyticData = useMemo(() => {
    if (analyticView === 'Mill') {
      const millMap = new Map();
      mills.forEach(m => millMap.set(Number(m.id), { name: m.name || m.code, cost: 0 }));

      const aggregateCost = (contracts: any[], defaultId: number) => {
        contracts.forEach(c => {
          const id = Number(c.mill_id) || defaultId;
          const cost = Number(c.distributed_cost || c.cost_idr) || 0;
          if (millMap.has(id)) millMap.get(id).cost += cost;
        });
      };

      aggregateCost(fixContracts, Number(mills[0]?.id));
      aggregateCost(varContracts, Number(mills[1]?.id));
      aggregateCost(oncallContracts, Number(mills[0]?.id));

      return Array.from(millMap.values())
        .filter(v => v.cost > 0)
        .sort((a, b) => b.cost - a.cost)
        .slice(0, 5);
    } else {
      const vendorMap = new Map();
      const processContracts = (contracts: any[]) => {
        contracts.forEach(c => {
          const vName = c.vendor?.name || c.transporter_carrier || 'Unknown Vendor';
          if (!vendorMap.has(vName)) vendorMap.set(vName, { name: vName, cost: 0 });
          vendorMap.get(vName).cost += (Number(c.distributed_cost || c.cost_idr) || 0);
        });
      };

      if (fixContracts.length === 0 && varContracts.length === 0 && oncallContracts.length === 0) {
        return [];
      }

      processContracts(fixContracts);
      processContracts(varContracts);
      processContracts(oncallContracts);

      return Array.from(vendorMap.values())
        .sort((a, b) => b.cost - a.cost)
        .slice(0, 5);
    }
  }, [analyticView, fixContracts, varContracts, oncallContracts, mills]);

  // 4. MOT Distribution
  const motDistributionData = useMemo(() => {
    const motMap = new Map();
    mots.forEach(m => motMap.set(Number(m.id), { name: m.name, count: 0 }));

    const processMot = (contracts: any[]) => {
      contracts.forEach(c => {
        const id = Number(c.mot_id);
        if (id && motMap.has(id)) motMap.get(id).count += 1;
      });
    };

    processMot(fixContracts);
    processMot(varContracts);
    processMot(oncallContracts);

    return Array.from(motMap.values()).filter(v => v.count > 0);
  }, [fixContracts, varContracts, oncallContracts, mots]);

  // --- List Data ---
  const latestAgreements = useMemo(() => {
    const all = [
      ...fixContracts.map(c => ({
        id: `fix-${c.id}`,
        rawId: c.id,
        resource: 'contract_dedicated_fix',
        vendor: c.vendor?.name || 'Unknown',
        date: formatDate(c.validity_start),
        msg: c.notes || `Dedicated Fix contract SPK: ${c.spk_number}`,
        type: 'Dedicated Fix',
        timestamp: c.updated_at || c.created_at
      })),
      ...varContracts.map(c => ({
        id: `var-${c.id}`,
        rawId: c.id,
        resource: 'contract_dedicated_var',
        vendor: c.vendor?.name || 'Unknown',
        date: formatDate(c.validity_start),
        msg: c.notes || `Dedicated Var contract SPK: ${c.spk_number}`,
        type: 'Dedicated Var',
        timestamp: c.updated_at || c.created_at
      })),
      ...oncallContracts.map(c => ({
        id: `oncall-${c.id}`,
        rawId: c.id,
        resource: 'contract_oncall',
        vendor: c.vendor?.name || 'Unknown',
        date: formatDate(c.validity_start),
        msg: c.notes || `Oncall contract SPK: ${c.spk_number}`,
        type: 'Oncall',
        timestamp: c.updated_at || c.created_at
      }))
    ];

    return all
      .filter(a => a.timestamp)
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  }, [fixContracts, varContracts, oncallContracts]);

  // Menyesuaikan style border bottom Card sesuai mode (Light/Dark)
  const cardHeaderStyle = {
    borderBottom: `1px solid ${token.colorSplit}`,
    paddingTop: 16
  };

  if (loading) {
    return (
      <Flex justify="center" align="center" style={{ height: 'calc(100vh - 64px)' }}>
        <Spin size="large"><div style={{ marginTop: 16, color: token.colorTextSecondary }}>Aggregating metrics...</div></Spin>
      </Flex>
    );
  }

  return (
    <div style={{ padding: '32px 40px', maxWidth: 1600, margin: "0 auto", minHeight: 'calc(100vh - 64px)' }}>
      {/* Header */}
      <Flex justify="space-between" align="center" style={{ marginBottom: 32 }}>
        <div>
          <Title level={2} style={{ margin: '0 0 4px 0', fontWeight: 700 }}>
            Overview Dashboard
          </Title>
          <Text type="secondary" style={{ fontSize: '14px', fontWeight: 500 }}>
            Last Update: {new Date().toLocaleDateString('en-US')}
          </Text>
        </div>
      </Flex>

      {/* KPI Cards */}
      <Row gutter={[24, 24]}>
        <Col xs={24} sm={12} lg={6}>
          <Card styles={{ body: { padding: '24px' } }} style={{ borderRadius: '12px', height: '100%', border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}>
            <Flex justify="space-between" style={{ marginBottom: 16 }}>
              <Text strong style={{ fontSize: '15px' }}>Total Landed Cost</Text>
              <div style={{ padding: '8px', backgroundColor: token.colorPrimaryBg, borderRadius: '8px', display: 'flex' }}>
                <DollarOutlined style={{ color: token.colorPrimary, fontSize: '18px' }} />
              </div>
            </Flex>
            <Title level={3} style={{ margin: '0 0 8px 0', fontWeight: 700 }}>{formatIDR(totalLandedCost)}</Title>
            <Text style={{ color: token.colorSuccess, fontSize: '12px', fontWeight: 600 }}>+12% <Text type="secondary" style={{ fontSize: '12px', fontWeight: 'normal' }}>from last month</Text></Text>
          </Card>
        </Col>

        <Col xs={24} sm={12} lg={6}>
          <Card styles={{ body: { padding: '24px' } }} style={{ borderRadius: '12px', height: '100%', border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}>
            <Flex justify="space-between" style={{ marginBottom: 16 }}>
              <Text strong style={{ fontSize: '15px' }}>Avg. Running Cost</Text>
              <div style={{ padding: '8px', backgroundColor: token.colorSuccessBg, borderRadius: '8px', display: 'flex' }}>
                <ThunderboltOutlined style={{ color: token.colorSuccess, fontSize: '18px' }} />
              </div>
            </Flex>
            <Title level={3} style={{ margin: '0 0 8px 0', fontWeight: 700 }}>{avgRunningCost} <span style={{ fontSize: 14, fontWeight: 'normal', color: token.colorTextSecondary }}>IDR/T/K</span></Title>
            <Text style={{ color: token.colorError, fontSize: '12px', fontWeight: 600 }}>-2.4% <Text type="secondary" style={{ fontSize: '12px', fontWeight: 'normal' }}>improved efficiency</Text></Text>
          </Card>
        </Col>

        <Col xs={24} sm={12} lg={6}>
          <Card styles={{ body: { padding: '24px' } }} style={{ borderRadius: '12px', height: '100%', border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}>
            <Flex justify="space-between" style={{ marginBottom: 16 }}>
              <Text strong style={{ fontSize: '15px' }}>Expiring Contracts</Text>
              <div style={{ padding: '8px', backgroundColor: token.colorWarningBg, borderRadius: '8px', display: 'flex' }}>
                <AlertOutlined style={{ color: token.colorWarning, fontSize: '18px' }} />
              </div>
            </Flex>
            <Title level={3} style={{ margin: '0 0 8px 0', fontWeight: 700, color: token.colorWarning }}>
              {expiringContracts.length} Contracts
            </Title>
            <Text type="secondary" style={{ fontSize: '13px' }}>Expires in &lt; 30 days</Text>
          </Card>
        </Col>

        <Col xs={24} sm={12} lg={6}>
          <Card styles={{ body: { padding: '24px' } }} style={{ borderRadius: '12px', height: '100%', border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}>
            <Flex justify="space-between" style={{ marginBottom: 16 }}>
              <Text strong style={{ fontSize: '15px' }}>Registered Vendors</Text>
              <div style={{ padding: '8px', backgroundColor: token.colorInfoBg, borderRadius: '8px', display: 'flex' }}>
                <CheckCircleOutlined style={{ color: token.colorInfo, fontSize: '18px' }} />
              </div>
            </Flex>
            <Title level={3} style={{ margin: '0 0 8px 0', fontWeight: 700, color: token.colorText }}>
              {vendors.length} Vendors
            </Title>
            <Text type="secondary" style={{ fontSize: '13px', display: 'block' }}>Total registered logistics partners</Text>
          </Card>
        </Col>
      </Row>

      {/* Analytics Row 1: Trend & Proporsi */}
      <Row gutter={[24, 24]} style={{ marginTop: 24 }}>
        <Col xs={24} lg={16}>
          <Card
            title={<span><BarChartOutlined style={{ marginRight: 8, color: token.colorPrimary }} />Logistics Cost Trend (Dedicated vs Oncall)</span>}
            styles={{ body: { padding: '24px', height: '340px' }, header: cardHeaderStyle }}
            style={{ borderRadius: '12px', height: '100%', border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}
          >
            <div style={{ width: "100%", minWidth: 0, minHeight: 300 }}>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={trendData} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={token.colorSplit} />
                  <XAxis
                    dataKey="month"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: token.colorTextSecondary, fontSize: 12 }}
                    dy={10}
                  />
                  <YAxis
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: token.colorTextSecondary, fontSize: 12 }}
                    width={60}
                    tickFormatter={(value) => {
                      if (value >= 1000000000) return `${(value / 1000000000).toFixed(1)}M`;
                      if (value >= 1000000) return `${(value / 1000000).toFixed(0)}Jt`;
                      return formatNumber(value);
                    }}
                  />
                  <RechartsTooltip
                    cursor={{ fill: token.colorFillAlter }}
                    contentStyle={{
                      backgroundColor: token.colorBgElevated,
                      border: `1px solid ${token.colorBorderSecondary}`,
                      borderRadius: "8px",
                      boxShadow: token.boxShadowSecondary,
                    }}
                    itemStyle={{ color: token.colorText, fontWeight: 500 }}
                    labelStyle={{ color: token.colorText, fontWeight: "bold", marginBottom: "8px" }}
                    formatter={(value: any, name: any) => [
                      `Rp ${formatNumber(value)}`,
                      name,
                    ]}
                  />
                  <Legend
                    iconType="circle"
                    wrapperStyle={{ fontSize: "12px", paddingTop: "15px", color: token.colorText }}
                  />
                  <Bar
                    dataKey="dedicated"
                    fill={token.colorPrimary}
                    radius={[4, 4, 0, 0]}
                    name="Dedicated Cost"
                    maxBarSize={40}
                  />
                  <Bar
                    dataKey="oncall"
                    fill={token.colorSuccess}
                    radius={[4, 4, 0, 0]}
                    name="Oncall Spot"
                    maxBarSize={40}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card
            title={<span><PieChartOutlined style={{ marginRight: 8, color: token.colorWarning }} />Active Contract Proportions</span>}
            styles={{ body: { padding: '24px', height: '340px' }, header: cardHeaderStyle }}
            style={{ borderRadius: '12px', height: '100%', border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}
          >
            <div style={{ width: "100%", minWidth: 0, minHeight: 210 }}>
              <ResponsiveContainer width="100%" height={210}>
                <PieChart>
                  <Pie
                    data={contractPropData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={85}
                    paddingAngle={5}
                    dataKey="value"
                  >
                    {contractPropData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <RechartsTooltip
                    contentStyle={{ backgroundColor: token.colorBgElevated, border: `1px solid ${token.colorBorderSecondary}`, borderRadius: '8px', color: token.colorText, boxShadow: token.boxShadowSecondary }}
                    itemStyle={{ color: token.colorText }}
                    formatter={(value: any) => `${value} Contracts`}
                  />
                </PieChart>
            </ResponsiveContainer>
            </div>

            <div style={{ marginTop: 16 }}>
              {contractPropData.map((item, idx) => (
                <Flex key={idx} justify="space-between" align="center" style={{ marginBottom: 8 }}>
                  <Space size={8}>
                    <div style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: COLORS[idx] }} />
                    <Text style={{ fontSize: 13 }}>{item.name}</Text>
                  </Space>
                  <Text strong style={{ fontSize: 13 }}>{item.value}</Text>
                </Flex>
              ))}
            </div>
          </Card>
        </Col>
      </Row>

      {/* Analytics Row 2: Interactive Top Spends & MOT Distribution */}
      <Row gutter={[24, 24]} style={{ marginTop: 24 }}>
        <Col xs={24} lg={16}>
          <Card
            title={
              <Space>
                <TrophyOutlined style={{ color: token.colorInfo }} />
                <span>Top Cost Absorption (Sort by Cost)</span>
              </Space>
            }
            extra={
              <Segmented
                options={['Vendor', 'Mill']}
                value={analyticView}
                onChange={(val) => setAnalyticView(val as 'Vendor' | 'Mill')}
              />
            }
            styles={{ body: { padding: '24px', height: '360px' }, header: cardHeaderStyle }}
            style={{ borderRadius: '12px', height: '100%', border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}
          >
            <div style={{ width: "100%", minWidth: 0, minHeight: 300 }}>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={sortedAnalyticData} layout="vertical" margin={{ top: 0, right: 30, left: 40, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={true} vertical={false} stroke={token.colorSplit} />
                  <XAxis type="number" hide />
                  <YAxis
                    dataKey="name"
                    type="category"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: token.colorText, fontSize: 12, fontWeight: 500 }}
                    width={140}
                  />
                  <RechartsTooltip
                    cursor={{ fill: token.colorFillSecondary }}
                    contentStyle={{ backgroundColor: token.colorBgElevated, border: `1px solid ${token.colorBorderSecondary}`, borderRadius: '8px', color: token.colorText, boxShadow: token.boxShadowSecondary }}
                    itemStyle={{ color: token.colorText }}
                    formatter={(value: any) => [`Rp ${formatNumber(value)}`, "Total Cost"]}
                  />
                  <Bar
                    dataKey="cost"
                    fill={analyticView === "Vendor" ? COLORS[4] : COLORS[6]}
                    radius={[0, 4, 4, 0]}
                    barSize={24}
                    label={{ position: "right", fill: token.colorTextSecondary, fontSize: 12, formatter: (val: any) => `Rp ${formatNumber(val)}` }}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card
            title={<span><PieChartOutlined style={{ marginRight: 8, color: token.colorSuccess }} />MoT Distribution</span>}
            styles={{ body: { padding: '24px', height: '360px' }, header: cardHeaderStyle }}
            style={{ borderRadius: '12px', height: '100%', border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}
          >
            <div style={{ width: "100%", minWidth: 0, minHeight: 210 }}>
              <ResponsiveContainer width="100%" height={210}>
                <PieChart>
                  <Pie
                    data={motDistributionData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={85}
                    paddingAngle={5}
                    dataKey="count"
                  >
                    {motDistributionData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[(index + 3) % COLORS.length]} />
                    ))}
                  </Pie>
                  <RechartsTooltip
                    contentStyle={{ backgroundColor: token.colorBgElevated, border: `1px solid ${token.colorBorderSecondary}`, borderRadius: '8px', color: token.colorText, boxShadow: token.boxShadowSecondary }}
                    itemStyle={{ color: token.colorText }}
                    formatter={(value: any) => `${value} Contracts`}
                  />
                </PieChart>
            </ResponsiveContainer>
            </div>

            <div style={{ marginTop: 16, maxHeight: '120px', overflowY: 'auto', paddingRight: '8px' }}>
              {motDistributionData.map((item, idx) => (
                <Flex key={idx} justify="space-between" align="center" style={{ marginBottom: 8 }}>
                  <Space size={8}>
                    <div style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: COLORS[(idx + 3) % COLORS.length] }} />
                    <Text style={{ fontSize: 13 }}>{item.name}</Text>
                  </Space>
                  <Text strong style={{ fontSize: 13 }}>{item.count}</Text>
                </Flex>
              ))}
            </div>
          </Card>
        </Col>
      </Row>

      {/* Tables Row */}
      <Row gutter={[24, 24]} style={{ marginTop: 24 }}>
        <Col xs={24} lg={12}>
          <Card
            title={<span><HistoryOutlined style={{ marginRight: 8, color: token.colorPrimary }} />Latest Agreements</span>}
            style={{ borderRadius: '12px', height: '100%', border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}
            styles={{ body: { padding: '0 24px 24px 24px' }, header: { borderBottom: 'none', paddingTop: 16 } }}
          >
            <Flex vertical gap={0} style={{ maxHeight: 330, overflowY: 'auto', paddingRight: 8 }}>
              {latestAgreements.map((item) => (
                <div
                  key={item.id}
                  style={{ 
                    padding: '16px 0', 
                    borderBottom: `1px solid ${token.colorSplit}`, 
                    cursor: 'pointer',
                    transition: 'opacity 0.2s'
                  }}
                  onClick={() => edit(item.resource, item.rawId)}
                  onMouseEnter={(e) => e.currentTarget.style.opacity = '0.8'}
                  onMouseLeave={(e) => e.currentTarget.style.opacity = '1'}
                >
                  <Flex vertical>
                    <Flex justify="space-between" align="center" style={{ marginBottom: 4 }}>
                      <Text strong style={{ fontSize: 14 }}>{item.vendor}</Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>{item.date}</Text>
                    </Flex>
                    <div>
                      <Text style={{ fontSize: 13, color: token.colorTextSecondary, display: 'block', marginBottom: 6 }}>{item.msg}</Text>
                      <Tag color={item.type === 'Oncall' ? 'green' : 'blue'} variant="filled">{item.type}</Tag>
                    </div>
                  </Flex>
                </div>
              ))}
            </Flex>
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card
            title={<span><AlertOutlined style={{ marginRight: 8, color: token.colorWarning }} />Expiring Contracts</span>}
            style={{ borderRadius: '12px', height: '100%', border: `1px solid ${token.colorBorderSecondary}`, boxShadow: token.boxShadowTertiary }}
            styles={{ body: { padding: '0 24px 24px 24px' }, header: { borderBottom: 'none', paddingTop: 16 } }}
          >
            <Flex vertical gap={12} style={{ maxHeight: 300, overflowY: 'auto', paddingRight: 8 }}>
              {expiringContracts.map((item: any, idx) => (
                <div
                  key={idx}
                  style={{ 
                    padding: '16px', 
                    backgroundColor: token.colorWarningBg, 
                    borderRadius: '8px', 
                    border: `1px solid ${token.colorWarningBorder}`, 
                    cursor: 'pointer',
                    transition: 'opacity 0.2s'
                  }}
                  onClick={() => edit(item.type === 'Fix' ? 'contract_dedicated_fix' : item.type === 'Var' ? 'contract_dedicated_var' : 'contract_oncall', item.id)}
                  onMouseEnter={(e) => e.currentTarget.style.opacity = '0.8'}
                  onMouseLeave={(e) => e.currentTarget.style.opacity = '1'}
                >
                  <Flex justify="space-between" align="center" style={{ width: '100%' }}>
                    <Space size={12}>
                      <div style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: token.colorWarning }} />
                      <Text strong style={{ fontSize: 13, color: token.colorWarningText }}>
                        SPK: {item.spk_number || "Unknown"} <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>({item.type})</Text>
                      </Text>
                    </Space>
                    <Space>
                      <Tag color="orange" variant="filled">{item.daysLeft} days left</Tag>
                    </Space>
                  </Flex>
                </div>
              ))}
            </Flex>
            {expiringContracts.length === 0 && (
              <Flex justify="center" align="center" style={{ height: 100 }}>
                <Text type="secondary">No contracts are expiring soon.</Text>
              </Flex>
            )}
          </Card>
        </Col>
      </Row>

    </div>
  );
}
