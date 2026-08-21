"use client";

import { useState, useRef, useEffect } from "react";
import { useShell } from "./ShellState";
import { INDIA_LOCATIONS, searchIndiaLocation, getSuggestedCity, type IndiaLocation } from "@/lib/locations";
import { Icon } from "@/components/ui/Icon";
import s from "./shell.module.css";

export function LocationSwitcher() {
  const { location, setLocation } = useShell();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<IndiaLocation[]>([]);
  const [searching, setSearching] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Debounced live geocoding search for ANY town / village / city in India
  useEffect(() => {
    if (!search || search.trim().length < 2) {
      setSearchResults([]);
      setSearching(false);
      return;
    }

    setSearching(true);
    const timer = setTimeout(async () => {
      try {
        const results = await searchIndiaLocation(search);
        setSearchResults(results);
      } finally {
        setSearching(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [search]);

  const filteredPreset = search
    ? INDIA_LOCATIONS.filter(
        (l) =>
          l.name.toLowerCase().includes(search.toLowerCase()) ||
          l.district.toLowerCase().includes(search.toLowerCase()) ||
          l.region.toLowerCase().includes(search.toLowerCase()),
      )
    : INDIA_LOCATIONS;

  const sortedPreset = [...filteredPreset].sort((a, b) => a.name.localeCompare(b.name));
  const suggestedCity = getSuggestedCity(search);

  return (
    <div className={s.panelWrap} ref={ref}>
      <button
        type="button"
        className={`${s.ctl} ${s.ctlBordered}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label="Select Andhra Pradesh city or town"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "6px",
          padding: "0 10px",
          background: "var(--surface)",
          border: "1px solid var(--line)",
          borderRadius: "var(--r-control)",
          height: "36px",
          fontSize: "0.8rem",
          fontWeight: 600,
          color: "var(--text)",
          cursor: "pointer",
        }}
      >
        <Icon name="map" size={13} />
        <span style={{ maxWidth: "140px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {location.name}
        </span>
        <Icon name="chevronDown" size={13} />
      </button>

      {open && (
        <div
          className={s.panel}
          style={{
            position: "absolute",
            top: "calc(100% + 8px)",
            right: 0,
            left: "auto",
            width: "360px",
            maxHeight: "460px",
            display: "flex",
            flexDirection: "column",
            gap: "8px",
            padding: "14px",
            zIndex: 100000,
            overflowY: "auto",
            gridTemplateColumns: "1fr",
            boxShadow: "0 20px 50px rgba(0,0,0,0.22), 0 4px 14px rgba(0,0,0,0.1)",
            border: "1px solid var(--line-strong, rgba(0,0,0,0.18))",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px", padding: "8px 10px", background: "var(--bg-sunken)", borderRadius: "8px", border: "1px solid var(--line)" }}>
            <Icon name="search" size={15} />
            <input
              type="text"
              placeholder="Search Andhra Pradesh cities, towns, mandals (A-Z)..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              autoFocus
              style={{
                border: "none",
                background: "transparent",
                outline: "none",
                fontSize: "0.82rem",
                width: "100%",
                fontFamily: "var(--font-ui)",
                color: "var(--text)",
              }}
            />
          </div>

          {/* Typo-Tolerant "Did You Mean?" Suggestion Banner */}
          {suggestedCity && (
            <div
              style={{
                padding: "8px 12px",
                background: "rgba(234, 88, 12, 0.09)",
                border: "1px solid rgba(234, 88, 12, 0.3)",
                borderRadius: "8px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                fontSize: "0.78rem",
                color: "var(--text)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span>
                  Did you mean{" "}
                  <strong style={{ color: "var(--accent)", fontWeight: 700 }}>
                    {suggestedCity.name}
                  </strong>
                  ?
                </span>
              </div>
              <button
                type="button"
                onClick={() => {
                  setLocation(suggestedCity);
                  setOpen(false);
                  setSearch("");
                }}
                style={{
                  background: "var(--accent)",
                  color: "#fff",
                  border: "none",
                  padding: "4px 10px",
                  borderRadius: "4px",
                  fontSize: "0.72rem",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Select
              </button>
            </div>
          )}

          {searching && (
            <div style={{ padding: "8px", fontSize: "0.75rem", color: "var(--muted)", textAlign: "center" }}>
              Searching Andhra Pradesh locations...
            </div>
          )}

          {searchResults.length > 0 && (
            <div>
              <div className={s.panelGroupLabel}>Andhra Pradesh Search Results</div>
              {searchResults.map((loc) => (
                <button
                  key={loc.id}
                  type="button"
                  onClick={() => {
                    setLocation(loc);
                    setOpen(false);
                    setSearch("");
                  }}
                  className={s.panelItem}
                  style={{ width: "100%", textAlign: "left", cursor: "pointer", border: "none", background: "transparent", padding: "6px 8px" }}
                >
                  <div>
                    <strong style={{ fontSize: "0.82rem", display: "block" }}>{loc.name}</strong>
                    <span style={{ fontSize: "0.7rem", color: "var(--muted)" }}>{loc.district} · {loc.region}</span>
                  </div>
                </button>
              ))}
            </div>
          )}

          <div>
            <div className={s.panelGroupLabel} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>Andhra Pradesh Cities & Towns (A-Z)</span>
              <span style={{ fontSize: "0.68rem", fontWeight: 500, color: "var(--accent)" }}>{sortedPreset.length} Locations</span>
            </div>
            {sortedPreset.map((loc) => {
              const active = loc.id === location.id;
              return (
                <button
                  key={loc.id}
                  type="button"
                  onClick={() => {
                    setLocation(loc);
                    setOpen(false);
                    setSearch("");
                  }}
                  className={s.panelItem}
                  data-active={active}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    cursor: "pointer",
                    border: "none",
                    background: active ? "rgba(234, 88, 12, 0.08)" : "transparent",
                    padding: "7px 10px",
                    borderRadius: "6px",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    transition: "background 0.15s ease",
                  }}
                >
                  <div>
                    <strong style={{ fontSize: "0.83rem", display: "block", color: active ? "var(--accent)" : "var(--text)" }}>
                      {loc.name}
                    </strong>
                    <span style={{ fontSize: "0.7rem", color: "var(--muted)" }}>
                      {loc.district} · {loc.cad_zone}
                    </span>
                  </div>
                  {active && <span style={{ fontSize: "0.7rem", color: "var(--accent)", fontWeight: 700 }}>Active</span>}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
