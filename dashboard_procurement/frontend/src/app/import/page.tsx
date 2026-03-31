"use client";

import { Upload, Button, Card, Typography, Tag, Alert, Space, Divider, App, Row, Col, Flex, Result } from "antd";
import { UploadOutlined, FileExcelOutlined, CheckCircleOutlined, CloudUploadOutlined, SaveOutlined } from "@ant-design/icons";
import { useState } from "react";
import { apiClient } from "@/lib/api-client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080/api/v1";

const { Title, Text } = Typography;

interface ParsedSheet {
  sheet_name: string;
  sheet_type: string;
  headers: string[];
  rows: any[];
}

interface ImportResponse {
  file_name: string;
  saved_as: string;
  sheets: ParsedSheet[];
  warnings: string[];
}

export default function ImportWizardPage() {
  const [fileList, setFileList] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<ImportResponse | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [confirmResult, setConfirmResult] = useState<any>(null);
  const { message } = App.useApp();

  const handleUpload = async () => {
    if (fileList.length === 0) {
      message.error("Please select an Excel file first.");
      return;
    }

    const formData = new FormData();
    formData.append("file", fileList[0]);

    setUploading(true);
    setResult(null);
    try {
      const response = await apiClient.post(`${API_URL}/import/excel`, formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      });
      message.success("File uploaded and parsed successfully.");
      setResult(response.data);
    } catch (error: any) {
      message.error(error.response?.data?.error || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const handleConfirm = async () => {
    if (!result) return;
    setConfirming(true);
    try {
      const response = await apiClient.post(`${API_URL}/import/confirm`, {
        saved_as: result.saved_as,
      });
      message.success("Data saved to database successfully!");
      setConfirmed(true);
      setConfirmResult(response.data.result);
    } catch (error: any) {
      message.error(error.response?.data?.error || "Confirm import failed");
    } finally {
      setConfirming(false);
    }
  };

  const handleReset = () => {
    setFileList([]);
    setResult(null);
    setConfirmed(false);
    setConfirmResult(null);
  };



  return (
    <div style={{ padding: '32px 40px', maxWidth: 1400, margin: "0 auto", minHeight: 'calc(100vh - 64px)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 32 }}>
        <div>
          <Title level={2} style={{ margin: '0 0 8px 0', fontWeight: 700 }}>
            Data Import Wizard
          </Title>
        </div>
      </div>

      <div style={{ maxWidth: 800, margin: '0 auto' }}>
        <Card 
          title={<Space><FileExcelOutlined /> Upload Excel Template</Space>} 
          variant="borderless" 
          style={{ borderRadius: '12px', boxShadow: "none" }}
        >
          <div style={{ marginBottom: 24 }}>
            <Text type="secondary" style={{ display: "block", marginBottom: 16 }}>
              Upload your Excel template containing latest procurement pricing. The system will automatically detect the sheet types (Dedicated Fix, Dedicated Var, Oncall) and parse them into the required structure.
            </Text>
            <Upload
              beforeUpload={(file) => {
                setFileList([file]);
                return false;
              }}
              fileList={fileList}
              onRemove={() => {
                setFileList([]);
                setResult(null);
              }}
              maxCount={1}
              accept=".xlsx, .xls"
            >
              <Button icon={<UploadOutlined />}>Select Excel File</Button>
            </Upload>
          </div>
          
          <Button
            onClick={handleUpload}
            disabled={fileList.length === 0}
            loading={uploading}
            size="large"
            style={{ width: "100%", borderRadius: '6px' }}
          >
            {uploading ? "Parsing Document..." : "Upload & Parse Data"}
          </Button>
        </Card>

        {result && (
          <div style={{ marginTop: 32 }}>
            <Title level={4}>Import Status Report</Title>
            <Text type="secondary">Processed File: <strong>{result.file_name}</strong></Text>
            
            {result.warnings && result.warnings.length > 0 && (
              <Alert
                message="Data Validation Warnings"
                description={
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {result.warnings.map((item, idx) => <Text key={idx} type="danger">• {item}</Text>)}
                  </div>
                }
                type="warning"
                showIcon
                style={{ marginTop: 16, marginBottom: 16, borderRadius: '8px' }}
              />
            )}

            <div style={{ marginTop: 24 }}>
              {result.sheets.filter(s => s.sheet_type !== "unknown" && s.rows.length > 0).length === 0 ? (
                <Alert message="No recognizable data rows found in the sheets." type="info" showIcon />
              ) : (
                <>
                  <Row gutter={[16, 16]}>
                    {result.sheets.filter(s => s.sheet_type !== "unknown" && s.rows.length > 0).map((sheet, index) => (
                      <Col xs={24} md={12} key={index}>
                        <Card style={{ borderRadius: '8px', boxShadow: 'none' }}>
                          <Flex vertical style={{ width: "100%" }}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                              <Text strong>{sheet.sheet_name}</Text>
                              <Tag color="default">{sheet.sheet_type.replace("_", " ").toUpperCase()}</Tag>
                            </div>
                            <Divider style={{ margin: "12px 0" }} />
                            <div>
                              <CheckCircleOutlined style={{ color: "#10b981", marginRight: 8 }} />
                              <Text>{sheet.rows.length} rows parsed successfully.</Text>
                            </div>
                            <div style={{ marginTop: 8 }}>
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                {sheet.headers.length} columns detected and loaded.
                              </Text>
                            </div>
                          </Flex>
                        </Card>
                      </Col>
                    ))}
                  </Row>

                  {!confirmed ? (
                    <div style={{ marginTop: 24, display: 'flex', gap: 12 }}>
                      <Button
                        icon={<SaveOutlined />}
                        size="large"
                        loading={confirming}
                        onClick={handleConfirm}
                        style={{ flex: 1, borderRadius: '6px' }}
                      >
                        {confirming ? "Saving to Database..." : "Confirm & Save to Database"}
                      </Button>
                      <Button size="large" onClick={handleReset} type="primary" style={{ borderRadius: '6px' }}>
                        Cancel
                      </Button>
                    </div>
                  ) : (
                    <Result
                      status={confirmResult?.errors?.length > 0 ? "warning" : "success"}
                      title={confirmResult?.errors?.length > 0 ? "Import Completed with Warnings" : "Data Imported Successfully!"}
                      subTitle={
                        confirmResult ? (
                          <div>
                            <Text>Dedicated Fix: <strong>{confirmResult.dedicated_fix_inserted}</strong> rows</Text><br/>
                            <Text>Dedicated Var: <strong>{confirmResult.dedicated_var_inserted}</strong> rows</Text><br/>
                            <Text>Oncall: <strong>{confirmResult.oncall_inserted}</strong> rows</Text>
                            {confirmResult.errors && confirmResult.errors.length > 0 && (
                              <Alert
                                message={`${confirmResult.errors.length} error(s) during import`}
                                description={
                                  <div style={{ maxHeight: 200, overflow: 'auto' }}>
                                    {confirmResult.errors.map((e: string, i: number) => <div key={i}>• {e}</div>)}
                                  </div>
                                }
                                type="warning"
                                showIcon
                                style={{ marginTop: 16, textAlign: 'left' }}
                              />
                            )}
                          </div>
                        ) : "All data has been saved."
                      }
                      extra={[
                        <Button key="new" onClick={handleReset}>Upload Another File</Button>
                      ]}
                    />
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
