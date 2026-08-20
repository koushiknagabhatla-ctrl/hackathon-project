"use client";

import { useState, useRef, useEffect } from "react";
import { useShell } from "./ShellState";
import { INDIA_LOCATIONS, searchIndiaLocation, type IndiaLocation } from "@/lib/locations";
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

    const timer = setTimeout(async () => {
      setSearching(true);
      const results = await searchIndiaLocation(search);
      setSearchResults(results);
      setSearching(false);
    }, 300);

    return () => clearTimeout(timer);
  }, [search]);

  const filteredPreset = search
    ? INDIA_LOCATIONS.filter(
        (l) =>
          l.name.toLowerCase().includes(search.toLowerCase()) ||
          l.state.toLowerCase().includes(search.toLowerCase()),
      )
    : INDIA_LOCATIONS;

  return (
    <div className={s.panelWrap} ref={ref}>
      <button
        type="button"
        className={`${s.ctl} ${s.ctlBordered}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label="Select location in India"
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
        <span style={{ color: "var(--accent)" }}>📍</span>
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
            left: 0,
            right: "auto",
            width: "320px",
            maxHeight: "420px",
            display: "flex",
            flexDirection: "column",
            gap: "8px",
            padding: "12px",
            zIndex: 100000,
            overflowY: "auto",
            gridTemplateColumns: "1fr",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "6px", padding: "6px 8px", background: "var(--bg-sunken)", borderRadius: "6px", border: "1px solid var(--line)" }}>
            <Icon name="search" size={14} />
            <input
              type="text"
              placeholder="Search ANY city, town or state in India..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              autoFocus
              style={{
                border: "none",
                background: "transparent",
                outline: "none",
                fontSize: "0.8rem",
                width: "100%",
                fontFamily: "var(--font-ui)",
              }}
            />
          </div>

          {searching && (
            <div style={{ padding: "8px", fontSize: "0.75rem", color: "var(--muted)", textAlign: "center" }}>
              Searching nationwide geocoding...
            </div>
          )}

          {searchResults.length > 0 && (
            <div>
              <div className={s.panelGroupLabel}>Search Results (India)</div>
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
                    <span style={{ fontSize: "0.7rem", color: "var(--muted)" }}>{loc.state}</span>
                  </div>
                </button>
              ))}
            </div>
          )}

          <div>
            <div className={s.panelGroupLabel}>Major Metro & Smart Cities</div>
            {filteredPreset.map((loc) => {
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
                    padding: "6px 8px",
                    borderRadius: "4px",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <div>
                    <strong style={{ fontSize: "0.82rem", display: "block", color: active ? "var(--accent)" : "var(--text)" }}>
                      {loc.name}
                    </strong>
                    <span style={{ fontSize: "0.7rem", color: "var(--muted)" }}>
                      {loc.state} · {loc.cad_zone}
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
