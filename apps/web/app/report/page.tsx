"use client";

/**
 * Auralis Civic Issue Reporting & AI Visual Inspection — /report
 *
 * Citizen reporting portal featuring automated computer vision hazard detection,
 * spatial deduplication, department routing, SLA computation, and evidence minting.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, useApi } from "@/lib/api";
import s from "./report.module.css";

interface CivicReportItem {
  id: string;
  category: string;
  title: string;
  description: string;
  latitude: number;
  longitude: number;
  address: string | null;
  severity: "low" | "medium" | "high" | "critical";
  status: "submitted" | "verified" | "in_progress" | "resolved" | "rejected";
  annotated_image: string | null;
  vision_detections: Array<{ label: string; confidence: number; box: number[]; category: string }>;
  ai_verification: { ai_verified?: boolean; confidence?: number; visual_summary?: string; engine?: string };
  assigned_department: string;
  sla_deadline: string;
  corroboration_count: number;
  evidence_id: string | null;
  created_at: string;
}

interface ReportStats {
  total_reports: number;
  pending_count: number;
  resolved_count: number;
  by_category: Record<string, number>;
  by_department: Record<string, number>;
  by_severity: Record<string, number>;
}

const CATEGORIES = [
  { id: "pothole", label: "Pothole", icon: "🕳️" },
  { id: "garbage_overflow", label: "Garbage Dump", icon: "🗑️" },
  { id: "waterlogging", label: "Waterlogging", icon: "🌊" },
  { id: "broken_streetlight", label: "Streetlight Out", icon: "💡" },
  { id: "road_blockage", label: "Road Blockage", icon: "🚧" },
  { id: "fallen_tree", label: "Fallen Tree", icon: "🌳" },
  { id: "traffic_congestion", label: "Traffic Hazard", icon: "🚗" },
  { id: "fire_hazard", label: "Fire / Hazard", icon: "🔥" },
  { id: "infrastructure_damage", label: "Damaged Asset", icon: "🏗️" },
  { id: "other", label: "Other Issue", icon: "📋" },
];

const SEVERITIES = [
  { id: "low", label: "Low", sla: "72h SLA" },
  { id: "medium", label: "Medium", sla: "24h SLA" },
  { id: "high", label: "High", sla: "12h SLA" },
  { id: "critical", label: "Critical", sla: "4h SLA" },
];

export default function ReportPage() {
  const [activeTab, setActiveTab] = useState<"submit" | "feed">("submit");

  // Form State
  const [category, setCategory] = useState<string>("pothole");
  const [title, setTitle] = useState<string>("");
  const [description, setDescription] = useState<string>("");
  const [latitude, setLatitude] = useState<number>(16.5062);
  const [longitude, setLongitude] = useState<number>(80.6480);
  const [address, setAddress] = useState<string>("MG Road, Benz Circle, Vijayawada");
  const [severity, setSeverity] = useState<"low" | "medium" | "high" | "critical">("medium");
  const [imageData, setImageData] = useState<string | null>(null);
  const [annotatedPreview, setAnnotatedPreview] = useState<string | null>(null);
  const [visionAnalysis, setVisionAnalysis] = useState<any>(null);
  const [isAnalyzingVision, setIsAnalyzingVision] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitSuccess, setSubmitSuccess] = useState<any>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Feed & Stats Data
  const { data: reportsData, loading: reportsLoading, reload: reloadReports } = useApi<{ reports: CivicReportItem[]; count: number }>("/v1/reports");
  const { data: statsData, reload: reloadStats } = useApi<ReportStats>("/v1/reports/stats/overview");

  // Geolocation
  const handleGetLocation = () => {
    if ("geolocation" in navigator) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          setLatitude(parseFloat(pos.coords.latitude.toFixed(4)));
          setLongitude(parseFloat(pos.coords.longitude.toFixed(4)));
        },
        () => {
          setLatitude(16.5062);
          setLongitude(80.6480);
        }
      );
    }
  };

  // Image Upload & Automated AI Vision Trigger
  const handleImageFile = async (file: File) => {
    const reader = new FileReader();
    reader.onload = async (e) => {
      const b64 = e.target?.result as string;
      setImageData(b64);
      setAnnotatedPreview(b64);
      setIsAnalyzingVision(true);
      setVisionAnalysis(null);

      try {
        const res = await api.post<any>("/v1/vision/analyze", {
          image: b64,
          hint_category: category,
        });

        setVisionAnalysis(res);
        if (res.annotated_image_base64) {
          setAnnotatedPreview(res.annotated_image_base64);
        }
        if (res.primary_category && res.confidence >= 0.65) {
          setCategory(res.primary_category);
        }
        if (res.severity) {
          setSeverity(res.severity);
        }
      } catch (err) {
        console.warn("Vision analysis error:", err);
      } finally {
        setIsAnalyzingVision(false);
      }
    };
    reader.readAsDataURL(file);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!description.trim() || isSubmitting) return;

    setIsSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);

    try {
      const res = await api.post<any>("/v1/reports", {
        category,
        title: title || `${category.replace("_", " ").toUpperCase()} near ${address}`,
        description,
        latitude,
        longitude,
        address,
        severity,
        image: imageData,
      });

      setSubmitSuccess(res);
      // Reset form
      setDescription("");
      setTitle("");
      setImageData(null);
      setAnnotatedPreview(null);
      setVisionAnalysis(null);

      reloadReports();
      reloadStats();
    } catch (err: any) {
      setSubmitError(err?.message || "Failed to submit report. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleStatusUpdate = async (reportId: string, newStatus: string) => {
    try {
      await api.post(`/v1/reports/${reportId}/status`, { status: newStatus });
      reloadReports();
      reloadStats();
    } catch (err) {
      console.error("Status update failed:", err);
    }
  };

  const reports = reportsData?.reports || [];
  const stats = statsData || { total_reports: reports.length, pending_count: reports.filter(r => r.status !== 'resolved').length, resolved_count: reports.filter(r => r.status === 'resolved').length, by_category: {}, by_department: {}, by_severity: {} };

  return (
    <div className={s.reportPage}>
      {/* Header */}
      <div className={s.pageHeader}>
        <h1>Civic Issue Reporting</h1>
        <p>
          Report urban infrastructure defects, potholes, flooding, or safety hazards.
          Images are verified using computer vision with automated department routing and SLA assignment.
        </p>
      </div>

      {/* Stats Cards */}
      <div className={s.statsRow}>
        <div className={s.statCard}>
          <span className={s.statNumber}>{stats.total_reports}</span>
          <span className={s.statLabel}>Total Reports</span>
        </div>
        <div className={s.statCard}>
          <span className={s.statNumber} style={{ color: "var(--warn)" }}>{stats.pending_count}</span>
          <span className={s.statLabel}>Pending Triage</span>
        </div>
        <div className={s.statCard}>
          <span className={s.statNumber} style={{ color: "var(--ok)" }}>{stats.resolved_count}</span>
          <span className={s.statLabel}>Resolved</span>
        </div>
        <div className={s.statCard}>
          <span className={s.statNumber} style={{ color: "var(--accent)" }}>AI</span>
          <span className={s.statLabel}>Vision Verified</span>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className={s.tabs}>
        <button
          className={s.tabBtn}
          data-active={activeTab === "submit"}
          onClick={() => setActiveTab("submit")}
        >
          📝 Submit New Report
        </button>
        <button
          className={s.tabBtn}
          data-active={activeTab === "feed"}
          onClick={() => setActiveTab("feed")}
        >
          📋 Live City Issue Feed ({reports.length})
        </button>
      </div>

      {activeTab === "submit" ? (
        <div className={s.layoutGrid}>
          {/* Left Column: Form */}
          <form className={s.panel} onSubmit={handleSubmit}>
            <h2 className={s.panelTitle}>
              <span>📍</span> Report Issue
            </h2>

            {/* Category Selector */}
            <div className={s.formGroup}>
              <label className={s.label}>Issue Category</label>
              <div className={s.categoryGrid}>
                {CATEGORIES.map((cat) => (
                  <button
                    type="button"
                    key={cat.id}
                    className={s.categoryBtn}
                    data-selected={category === cat.id}
                    onClick={() => setCategory(cat.id)}
                  >
                    <span className={s.categoryIcon}>{cat.icon}</span>
                    <span>{cat.label}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Photo Upload Dropzone */}
            <div className={s.formGroup}>
              <label className={s.label}>Photo Attachment (AI Visual Inspection)</label>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                style={{ display: "none" }}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleImageFile(file);
                }}
              />
              <div
                className={s.dropZone}
                data-has-image={!!annotatedPreview}
                onClick={() => !annotatedPreview && fileInputRef.current?.click()}
              >
                {annotatedPreview ? (
                  <div className={s.imagePreviewContainer}>
                    <img src={annotatedPreview} alt="Inspection Preview" className={s.imagePreview} />
                    <button
                      type="button"
                      className={s.removeImageBtn}
                      onClick={(e) => {
                        e.stopPropagation();
                        setImageData(null);
                        setAnnotatedPreview(null);
                        setVisionAnalysis(null);
                      }}
                      title="Remove image"
                    >
                      ×
                    </button>
                  </div>
                ) : (
                  <div className={s.uploadPrompt}>
                    <span className={s.uploadIcon}>📷</span>
                    <strong>Click or drop photo here</strong>
                    <span>Instant AI object & hazard detection</span>
                  </div>
                )}
              </div>
            </div>

            {/* Vision AI Feedback Badge */}
            {isAnalyzingVision && (
              <div className={s.visionBadge}>
                <div className={s.visionBadgeHeader}>
                  <span>🔍 Running Computer Vision Analysis...</span>
                </div>
              </div>
            )}

            {visionAnalysis && !isAnalyzingVision && (
              <div className={s.visionBadge}>
                <div className={s.visionBadgeHeader}>
                  <span>✨ Vision AI: {visionAnalysis.primary_category?.replace("_", " ").toUpperCase()}</span>
                  <span>{(visionAnalysis.confidence * 100).toFixed(0)}% Conf</span>
                </div>
                <div className={s.visionBadgeBody}>
                  {visionAnalysis.visual_summary}
                  {visionAnalysis.detections?.length > 0 && ` (${visionAnalysis.detections.length} region(s) localized)`}
                </div>
              </div>
            )}

            {/* Description */}
            <div className={s.formGroup}>
              <label className={s.label}>Description & Specifics</label>
              <textarea
                className={s.textarea}
                placeholder="Describe the issue, size, impact, or landmark details..."
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                required
              />
            </div>

            {/* Location */}
            <div className={s.formGroup}>
              <label className={s.label}>Location / Coordinates</label>
              <div className={s.locationRow}>
                <input
                  type="number"
                  step="0.0001"
                  className={s.input}
                  placeholder="Latitude"
                  value={latitude}
                  onChange={(e) => setLatitude(parseFloat(e.target.value))}
                  required
                />
                <input
                  type="number"
                  step="0.0001"
                  className={s.input}
                  placeholder="Longitude"
                  value={longitude}
                  onChange={(e) => setLongitude(parseFloat(e.target.value))}
                  required
                />
                <button
                  type="button"
                  className={s.geoBtn}
                  onClick={handleGetLocation}
                  title="Use current GPS"
                >
                  📡 GPS
                </button>
              </div>
            </div>

            {/* Address / Landmark */}
            <div className={s.formGroup}>
              <label className={s.label}>Road Segment / Address</label>
              <input
                type="text"
                className={s.input}
                placeholder="e.g. Bandar Road, near Municipal Office"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
              />
            </div>

            {/* Severity & SLA */}
            <div className={s.formGroup}>
              <label className={s.label}>Urgency & Severity Level</label>
              <div className={s.severityRow}>
                {SEVERITIES.map((sev) => (
                  <button
                    type="button"
                    key={sev.id}
                    className={s.severityBtn}
                    data-level={sev.id}
                    data-selected={severity === sev.id}
                    onClick={() => setSeverity(sev.id as any)}
                  >
                    <span>{sev.label}</span>
                    <span>{sev.sla}</span>
                  </button>
                ))}
              </div>
            </div>

            {submitError && (
              <div style={{ color: "var(--bad)", fontSize: "var(--fs-sm)", background: "#ffebee", padding: "8px 12px", borderRadius: "8px" }}>
                ⚠️ {submitError}
              </div>
            )}

            {submitSuccess && (
              <div style={{ color: "var(--ok)", fontSize: "var(--fs-sm)", background: "#e8f5e9", padding: "12px", borderRadius: "8px", lineHeight: 1.4 }}>
                ✅ <strong>Report {submitSuccess.id} Submitted!</strong><br />
                Assigned to: <strong>{submitSuccess.assigned_department}</strong><br />
                SLA Deadline: {submitSuccess.sla_deadline?.slice(0, 16).replace("T", " ")} UTC
              </div>
            )}

            {/* Submit */}
            <button
              type="submit"
              className={s.submitBtn}
              disabled={isSubmitting || !description.trim()}
            >
              {isSubmitting ? "Submitting & Minting Evidence..." : "Submit Civic Report"}
            </button>
          </form>

          {/* Right Column: Triage Info & Map Context */}
          <div className={s.panel}>
            <h2 className={s.panelTitle}>
              <span>⚡</span> Autonomous Triage Pipeline
            </h2>
            <div style={{ fontSize: "var(--fs-sm)", color: "var(--text-soft)", lineHeight: 1.6, display: "flex", flexDirection: "column", gap: "14px" }}>
              <p>
                Every report submitted to Auralis passes through deterministic verification gates:
              </p>
              <ul style={{ margin: 0, paddingLeft: "20px" }}>
                <li><strong>Computer Vision Inspection:</strong> Analyzes uploaded imagery for structural surface defects, pooling water, or flame anomalies.</li>
                <li><strong>Spatial Deduplication:</strong> Correlates reports within 60 meters to prevent duplicate work orders and escalate priority.</li>
                <li><strong>Department Dispatch:</strong> Direct routing to Solid Waste Management, Roads & Bridges, or Drainage wings.</li>
                <li><strong>Evidence Ledger Minting:</strong> Cryptographically records the report hash and coordinates into the immutable audit ledger.</li>
              </ul>

              <div style={{ background: "var(--bg-sunken)", padding: "14px", borderRadius: "12px", marginTop: "8px" }}>
                <strong style={{ display: "block", marginBottom: "6px", color: "var(--text)" }}>Vijayawada Jurisdiction</strong>
                <span style={{ fontSize: "var(--fs-xs)", color: "var(--muted)" }}>
                  Zone: Urban Municipal Corporation (VMC)<br />
                  Emergency Corridor: Benz Circle – MG Road – Governorpet<br />
                  Data Tier: Open311 Protocol / Verified Evidence Ledger
                </span>
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* Live City Issue Feed Tab */
        <div className={s.reportsList}>
          {reportsLoading ? (
            <div style={{ padding: "32px", textAlign: "center", color: "var(--muted)" }}>
              Loading active reports from evidence ledger...
            </div>
          ) : reports.length === 0 ? (
            <div className={s.panel} style={{ textAlign: "center", padding: "48px" }}>
              <h3>No Civic Reports Found</h3>
              <p style={{ color: "var(--muted)" }}>All municipal zones are currently clear or no reports have been submitted yet.</p>
            </div>
          ) : (
            reports.map((rep) => (
              <div key={rep.id} className={s.reportCard}>
                <div className={s.reportCardHeader}>
                  <div>
                    <h3 className={s.reportTitle}>{rep.title}</h3>
                    <div className={s.reportMeta}>
                      {rep.address || `${rep.latitude.toFixed(3)}, ${rep.longitude.toFixed(3)}`} · Reported {rep.created_at.slice(0, 16).replace("T", " ")}
                    </div>
                  </div>
                  <div className={s.badgeGroup}>
                    <span className={s.severityBadge} data-sev={rep.severity}>
                      {rep.severity}
                    </span>
                    <span className={s.statusBadge} data-status={rep.status}>
                      {rep.status.replace("_", " ")}
                    </span>
                    {rep.corroboration_count > 1 && (
                      <span className={s.statusBadge} style={{ background: "var(--accent-wash)", color: "var(--accent-ink)" }}>
                        {rep.corroboration_count} Corroborations
                      </span>
                    )}
                  </div>
                </div>

                <div className={s.reportCardBody}>
                  {rep.description}
                </div>

                {rep.annotated_image && (
                  <div style={{ maxHeight: "200px", overflow: "hidden", borderRadius: "8px", background: "#000" }}>
                    <img src={rep.annotated_image} alt="Annotated Feature" style={{ width: "100%", height: "200px", objectFit: "cover" }} />
                  </div>
                )}

                {rep.ai_verification?.visual_summary && (
                  <div style={{ fontSize: "var(--fs-xs)", color: "var(--accent-ink)", background: "var(--accent-wash)", padding: "6px 10px", borderRadius: "6px" }}>
                    🔍 <strong>AI Analysis:</strong> {rep.ai_verification.visual_summary}
                  </div>
                )}

                <div className={s.reportCardFooter}>
                  <div>
                    🏢 <strong>{rep.assigned_department}</strong>
                    {rep.evidence_id && <span className={s.evidenceTag}> · Evidence #{rep.evidence_id.slice(-6)}</span>}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                    <span className={s.slaIndicator}>
                      ⏱️ SLA: {rep.sla_deadline?.slice(11, 16)} UTC
                    </span>
                    {rep.status !== "resolved" && (
                      <button
                        type="button"
                        onClick={() => handleStatusUpdate(rep.id, "resolved")}
                        style={{
                          background: "var(--ok)",
                          color: "#fff",
                          border: "none",
                          borderRadius: "6px",
                          padding: "3px 8px",
                          fontSize: "var(--fs-micro)",
                          cursor: "pointer",
                          fontWeight: 600,
                        }}
                      >
                        Mark Resolved
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
