"use client";

/**
 * Camera wall — /cctv
 *
 * Browsers cannot play RTSP, so tiles pull JPEG frames from the server-side
 * snapshot proxy. A town with no camera says so rather than showing another
 * city's junction.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, API_ORIGIN } from "@/lib/api";
import { useShell } from "@/components/shell/ShellState";
import { Icon } from "@/components/ui/Icon";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import s from "./cctv.module.css";

interface CameraRow {
  id: string;
  name: string;
  lat: number;
  lon: number;
  road_segment: string;
  enabled: boolean;
  authorized_by: string;
  sample_fps: number;
  distance_km: number;
  transport: string;
}

interface Signal {
  kind: string;
  confidence: number;
  labels: string[];
  detail: string;
}

interface PublicWebcam {
  id: string;
  title: string;
  lat: number;
  lon: number;
  distance_km: number | null;
  city: string;
  region: string;
  preview_url: string | null;
  player_url: string | null;
  detail_url: string | null;
}

interface WebcamResult {
  status: string;
  count: number;
  webcams: PublicWebcam[];
  detail?: string;
  provenance?: string;
}

interface AnalysisResult {
  status: string;
  error?: string;
  camera_name?: string;
  frames_analyzed?: number;
  elapsed_s?: number;
  scene?: { tracks: number; vehicles: number; people: number };
  signals?: Signal[];
}

const REFRESH_MS = 2500;

/** Tiles that are visibly stale are worse than tiles that admit it. */
function CameraTile({
  cam,
  tick,
  onOpen,
}: {
  cam: CameraRow;
  tick: number;
  onOpen: () => void;
}) {
  const [failed, setFailed] = useState(false);
  const src = `${API_ORIGIN}/v1/emergency/cctv/cameras/${cam.id}/snapshot?t=${tick}`;

  return (
    <button className={s.tile} onClick={onOpen} type="button">
      <div className={s.frame}>
        {failed ? (
          <div className={s.frameDown}>
            <Icon name="offline" size={18} />
            <span>No frame from this camera</span>
          </div>
        ) : (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            className={s.frameImg}
            src={src}
            alt={`Latest frame from ${cam.name}`}
            onError={() => setFailed(true)}
            onLoad={() => failed && setFailed(false)}
          />
        )}
        <span className={s.transport}>{cam.transport}</span>
      </div>

      <div className={s.tileMeta}>
        <span className={s.tileName}>{cam.name}</span>
        <span className={s.tileSub}>
          {cam.road_segment || `${cam.lat.toFixed(3)}, ${cam.lon.toFixed(3)}`}
          {" · "}
          {cam.distance_km < 1
            ? `${Math.round(cam.distance_km * 1000)} m`
            : `${cam.distance_km.toFixed(1)} km`}
        </span>
      </div>
    </button>
  );
}

export default function CctvPage() {
  const { location, queryCoords } = useShell();
  const { lat, lon } = queryCoords;

  const [cams, setCams] = useState<CameraRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const [live, setLive] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [analysing, setAnalysing] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [pub, setPub] = useState<WebcamResult | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get<{ count: number; cameras: CameraRow[] }>(
        `/v1/emergency/cctv/cameras/near?lat=${lat}&lon=${lon}&radius_km=60`
      );
      setCams(r.cameras);
      setError(null);
    } catch (e) {
      setError(e);
      setCams(null);
    } finally {
      setLoading(false);
    }
  }, [lat, lon]);

  useEffect(() => {
    void load();
  }, [load]);

  // Second path. Only consulted when the city has no registered camera, so a
  // place with its own feeds is never padded out with tourist webcams.
  useEffect(() => {
    if (cams === null || cams.length > 0) {
      setPub(null);
      return;
    }
    let alive = true;
    api
      .get<WebcamResult>(
        `/v1/emergency/cctv/public-webcams?lat=${lat}&lon=${lon}&radius_km=120`
      )
      .then((r) => alive && setPub(r))
      .catch(() => alive && setPub(null));
    return () => {
      alive = false;
    };
  }, [cams, lat, lon]);

  // Only pull frames while the tab is visible and live view is on: a hidden
  // tab quietly pulling every camera every 2.5s is a load nobody asked for.
  useEffect(() => {
    if (!live) return;
    const id = setInterval(() => {
      if (document.visibilityState === "visible") setTick((t) => t + 1);
    }, REFRESH_MS);
    return () => clearInterval(id);
  }, [live]);

  const open = useMemo(
    () => cams?.find((c) => c.id === openId) ?? null,
    [cams, openId]
  );

  const runAnalysis = async (id: string) => {
    setAnalysing(true);
    setAnalysis(null);
    try {
      const r = await api.post<AnalysisResult>(
        `/v1/emergency/cctv/cameras/${id}/analyze?seconds=12`,
        {}
      );
      setAnalysis(r);
    } catch (e) {
      setAnalysis({ status: "error", error: e instanceof Error ? e.message : String(e) });
    } finally {
      setAnalysing(false);
    }
  };

  return (
    <section className="container section">
      <div className={s.header}>
        <div>
          <span className="eyebrow">Operate · Camera wall</span>
          <h1>Cameras · {location.name}</h1>
          <p className={s.sub}>
            Feeds registered for this area. Frames are pulled from the camera on
            request; nothing is stored unless an incident is opened.
          </p>
        </div>
        <div className={s.headerActions}>
          <button
            type="button"
            className={`btn ${live ? "btn--primary" : ""}`}
            onClick={() => setLive((v) => !v)}
          >
            <Icon name={live ? "activity" : "offline"} size={15} />
            {live ? "Live" : "Paused"}
          </button>
          <button type="button" className="btn" onClick={() => void load()}>
            <Icon name="refresh" size={15} />
            Refresh
          </button>
          <button type="button" className="btn" onClick={() => setShowAdd((v) => !v)}>
            <Icon name="plus" size={15} />
            Add camera
          </button>
        </div>
      </div>

      {showAdd && <AddCameraForm lat={lat} lon={lon} onAdded={() => { setShowAdd(false); void load(); }} />}

      {error ? (
        <ErrorState error={error} onRetry={load} what="the camera registry" />
      ) : loading && !cams ? (
        <Skeleton lines={8} />
      ) : !cams || cams.length === 0 ? (
        <>
          <EmptyState
            icon="offline"
            title={`No camera is registered for ${location.name}`}
            body={
              "Andhra Pradesh traffic cameras are operated by the state police and the " +
              "Real Time Governance Society and are not published as an open stream, so a " +
              "feed has to be registered with the authority that granted access to it."
            }
            action={{ label: "Add a camera", onClick: () => setShowAdd(true) }}
          />
          <PublicWebcams result={pub} place={location.name} />
        </>
      ) : (
        <>
          <div className={s.grid}>
            {cams.map((c) => (
              <CameraTile
                key={c.id}
                cam={c}
                tick={tick}
                onOpen={() => {
                  setOpenId(c.id);
                  setAnalysis(null);
                }}
              />
            ))}
          </div>
          <p className={s.count}>
            {cams.length} camera{cams.length === 1 ? "" : "s"} within 60 km of{" "}
            {location.name}.
          </p>
        </>
      )}

      {open && (
        <div className={s.backdrop} onClick={() => setOpenId(null)}>
          <div className={s.detail} onClick={(e) => e.stopPropagation()}>
            <div className={s.detailHead}>
              <div>
                <h2>{open.name}</h2>
                <span className={s.detailSub}>
                  {open.road_segment || "—"} · authorised by {open.authorized_by} ·{" "}
                  sampling {open.sample_fps} fps
                </span>
              </div>
              <button
                className={s.close}
                onClick={() => setOpenId(null)}
                aria-label="Close"
              >
                <Icon name="close" size={16} />
              </button>
            </div>

            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              className={s.detailImg}
              src={`${API_ORIGIN}/v1/emergency/cctv/cameras/${open.id}/snapshot?t=${tick}`}
              alt={`Latest frame from ${open.name}`}
            />

            <div className={s.detailActions}>
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => void runAnalysis(open.id)}
                disabled={analysing}
              >
                <Icon name="activity" size={15} />
                {analysing ? "Analysing…" : "Analyse 12s"}
              </button>
              <span className={s.detailNote}>
                One camera is one witness. A detection here opens a suspected
                incident for review; it does not warn anyone on its own.
              </span>
            </div>

            {analysis && (
              <div className={s.analysis}>
                {analysis.status !== "ok" ? (
                  <p className={s.analysisErr}>
                    {analysis.error || "The camera could not be analysed."}
                  </p>
                ) : (
                  <>
                    <div className={s.analysisStats}>
                      <span>
                        <strong>{analysis.frames_analyzed}</strong> frames
                      </span>
                      <span>
                        <strong>{analysis.scene?.vehicles ?? 0}</strong> vehicles
                      </span>
                      <span>
                        <strong>{analysis.scene?.people ?? 0}</strong> people
                      </span>
                      <span>{analysis.elapsed_s}s</span>
                    </div>
                    {analysis.signals && analysis.signals.length > 0 ? (
                      <ul className={s.signals}>
                        {analysis.signals.map((sig, i) => (
                          <li key={i} className={s.signal}>
                            <span className={s.signalKind}>
                              {sig.kind.replace(/_/g, " ")}
                            </span>
                            <span className={s.signalConf}>
                              {Math.round(sig.confidence * 100)}% confidence
                            </span>
                            <span className={s.signalDetail}>{sig.detail}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className={s.analysisNone}>
                        No incident signature in this window.
                      </p>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function AddCameraForm({
  lat,
  lon,
  onAdded,
}: {
  lat: number;
  lon: number;
  onAdded: () => void;
}) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [authorizedBy, setAuthorizedBy] = useState("");
  const [segment, setSegment] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.post<{ status: string; error?: string; camera_id?: string }>(
        "/v1/emergency/cctv/cameras",
        {
          name,
          stream_url: url,
          lat,
          lon,
          authorized_by: authorizedBy,
          road_segment: segment,
        }
      );
      if (r.status === "ok") {
        setName("");
        setUrl("");
        setAuthorizedBy("");
        setSegment("");
        onAdded();
      } else {
        setMsg(r.error || "The camera could not be registered.");
      }
    } catch (err) {
      setMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className={s.addForm} onSubmit={submit}>
      <div className={s.addGrid}>
        <label className={s.field}>
          <span className="label">Camera name</span>
          <input
            className={s.input}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Benz Circle north approach"
            required
          />
        </label>
        <label className={s.field}>
          <span className="label">Stream URL</span>
          <input
            className={s.input}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="rtsp://user:pass@host:554/stream1"
            required
          />
        </label>
        <label className={s.field}>
          <span className="label">Road segment</span>
          <input
            className={s.input}
            value={segment}
            onChange={(e) => setSegment(e.target.value)}
            placeholder="MG Road"
          />
        </label>
        <label className={s.field}>
          <span className="label">Authorised by</span>
          <input
            className={s.input}
            value={authorizedBy}
            onChange={(e) => setAuthorizedBy(e.target.value)}
            placeholder="Name of the officer granting access"
            required
          />
        </label>
      </div>
      <div className={s.addFoot}>
        <span className={s.addNote}>
          Registered at the coordinates of the selected place. Access to a
          camera is somebody&rsquo;s decision, so the record names them.
        </span>
        <button type="submit" className="btn btn--primary" disabled={busy}>
          {busy ? "Registering…" : "Register camera"}
        </button>
      </div>
      {msg && <p className={s.addErr}>{msg}</p>}
    </form>
  );
}


/**
 * Fallback path: cameras their operators chose to publish. These are not the
 * city's own traffic cameras and the section says so, because a harbour webcam
 * 40 km away answers a different question than a junction camera does.
 */
function PublicWebcams({
  result,
  place,
}: {
  result: WebcamResult | null;
  place: string;
}) {
  if (!result) return null;

  if (result.status === "unconfigured") {
    return (
      <div className={s.fallback}>
        <h2 className={s.fallbackTitle}>Public webcams</h2>
        <p className={s.fallbackNote}>
          A second index of webcams whose operators published them can be
          searched near {place}. It needs <code>WINDY_WEBCAMS_API_KEY</code> to
          be set. Unsecured cameras are deliberately not indexed here.
        </p>
      </div>
    );
  }

  if (result.status !== "ok" || result.count === 0) {
    return (
      <div className={s.fallback}>
        <h2 className={s.fallbackTitle}>Public webcams</h2>
        <p className={s.fallbackNote}>
          {result.detail || `No published webcam was found near ${place}.`}
        </p>
        {result.status === "no_coverage" && (
          <p className={s.fallbackNote}>
            This is a gap in the public index, not a fault. Registering the
            city&rsquo;s own camera above is the path that shows its junctions.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className={s.fallback}>
      <h2 className={s.fallbackTitle}>
        Public webcams near {place} ({result.count})
      </h2>
      <p className={s.fallbackNote}>
        Published by their operators, not city traffic cameras. Each links to
        the directory entry it came from.
      </p>
      <div className={s.grid}>
        {result.webcams.map((w) => (
          <a
            key={w.id}
            className={s.tile}
            href={w.detail_url || w.player_url || "#"}
            target="_blank"
            rel="noreferrer"
          >
            <div className={s.frame}>
              {w.preview_url ? (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img className={s.frameImg} src={w.preview_url} alt={w.title} />
              ) : (
                <div className={s.frameDown}>
                  <Icon name="offline" size={18} />
                  <span>No preview published</span>
                </div>
              )}
              <span className={s.transport}>public</span>
            </div>
            <div className={s.tileMeta}>
              <span className={s.tileName}>{w.title}</span>
              <span className={s.tileSub}>
                {[w.city, w.region].filter(Boolean).join(", ") || "—"}
                {w.distance_km !== null ? ` · ${w.distance_km.toFixed(1)} km` : ""}
              </span>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
