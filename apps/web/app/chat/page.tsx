"use client";

/**
 * Auralis AI Chat — /chat
 *
 * Claude-Inspired World-Class Conversational Civic Intelligence Interface.
 * Connected to live municipal telemetry across 206 Indian cities with Zero-Fabrication enforcement.
 * Powered by local fine-tuned Qwen2.5-1.5B (Auralis AP Urban Intelligence) with tool execution.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useShell } from "@/components/shell/ShellState";
import { INDIA_LOCATIONS, type IndiaLocation } from "@/lib/locations";
import s from "./chat.module.css";

interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

interface ToolResult {
  tool_use_id: string;
  name: string;
  result: Record<string, unknown>;
}

interface ChatResponse {
  session_id: string;
  message: string;
  tool_calls: ToolCall[];
  tool_results: ToolResult[];
  model: string;
  degraded: boolean;
  timestamp: string;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  toolCalls?: ToolCall[];
  toolResults?: ToolResult[];
  degraded?: boolean;
  model?: string;
  cityName?: string;
}

interface Session {
  id: string;
  title: string;
  cityName: string;
  lastActive: string;
  messageCount: number;
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

/** Rich Markdown Renderer with clean block formatting */
function renderMarkdown(text: string): React.ReactNode[] {
  const lines = text.split("\n");
  const nodes: React.ReactNode[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) {
      nodes.push(<div key={`sp-${i}`} className={s.spacer} />);
      continue;
    }

    // Header 3: ### Header
    if (line.startsWith("### ")) {
      nodes.push(
        <h4 key={`h3-${i}`} className={s.mdH3}>
          {line.replace("### ", "")}
        </h4>
      );
      continue;
    }

    // Header 2: ## Header
    if (line.startsWith("## ")) {
      nodes.push(
        <h3 key={`h2-${i}`} className={s.mdH2}>
          {line.replace("## ", "")}
        </h3>
      );
      continue;
    }

    // Bullet item
    if (line.startsWith("• ") || line.startsWith("- ") || line.startsWith("* ")) {
      const content = line.replace(/^[•\-*]\s+/, "");
      nodes.push(
        <div key={`li-${i}`} className={s.mdListItem}>
          <span className={s.bulletPoint}>•</span>
          <div>{renderInline(content, i)}</div>
        </div>
      );
      continue;
    }

    // Default paragraph
    nodes.push(
      <p key={`p-${i}`} className={s.mdP}>
        {renderInline(line, i)}
      </p>
    );
  }

  return nodes;
}

function renderInline(text: string, lineIdx: number): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  // Match bold **text** or code `text`
  const regex = /(\*\*(.+?)\*\*|`(.+?)`)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    if (match[2]) {
      // Bold
      parts.push(
        <strong key={`b-${lineIdx}-${match.index}`} className={s.boldText}>
          {match[2]}
        </strong>
      );
    } else if (match[3]) {
      // Code
      parts.push(
        <code key={`c-${lineIdx}-${match.index}`} className={s.codePill}>
          {match[3]}
        </code>
      );
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts.length > 0 ? parts : [text];
}

export default function ChatPage() {
  const { location, setLocation } = useShell();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [cityModalOpen, setCityModalOpen] = useState(false);
  const [citySearch, setCitySearch] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [expandedToolId, setExpandedToolId] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const recognitionRef = useRef<any>(null);

  const activeCityName = location.id === "all_india" ? "National" : location.name.split("/")[0].trim();
  const activeLat = location.coordinates[1];
  const activeLon = location.coordinates[0];

  // Dynamic quick prompt suggestions customized to the active city
  const quickActions = [
    {
      emoji: "🌤️",
      title: "Weather Telemetry",
      subtitle: "Temperature, precipitation & wind",
      prompt: `What's the current verified weather in ${activeCityName}?`,
    },
    {
      emoji: "🚨",
      title: "Active Hazards",
      subtitle: "Incidents & emergency alerts",
      prompt: `Are there any active civic incidents or hazard advisories in ${activeCityName}?`,
    },
    {
      emoji: "🏥",
      title: "Emergency Locator",
      subtitle: "Trauma centers & hospitals",
      prompt: `Find nearest hospitals and emergency medical centers in ${activeCityName}`,
    },
    {
      emoji: "🚗",
      title: "Traffic & Routing",
      subtitle: "Corridor delay & safe routes",
      prompt: `What is the traffic congestion status and safe corridor in ${activeCityName}?`,
    },
  ];

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading, scrollToBottom]);

  // Load chat session history from local storage
  useEffect(() => {
    try {
      const saved = localStorage.getItem("auralis_chat_sessions");
      if (saved) {
        setSessions(JSON.parse(saved));
      }
    } catch {
      // Ignore
    }
  }, []);

  const saveCurrentSession = useCallback(
    (newMessages: Message[], sid: string) => {
      if (newMessages.length === 0) return;
      const firstUserMsg = newMessages.find((m) => m.role === "user");
      const title = firstUserMsg ? firstUserMsg.content.slice(0, 36) + (firstUserMsg.content.length > 36 ? "..." : "") : "Civic Consultation";

      setSessions((prev) => {
        const filtered = prev.filter((s) => s.id !== sid);
        const updated: Session = {
          id: sid,
          title,
          cityName: activeCityName,
          lastActive: new Date().toISOString(),
          messageCount: newMessages.length,
        };
        const nextSessions = [updated, ...filtered].slice(0, 20);
        try {
          localStorage.setItem("auralis_chat_sessions", JSON.stringify(nextSessions));
        } catch {
          // Ignore
        }
        return nextSessions;
      });
    },
    [activeCityName]
  );

  const startNewChat = () => {
    if (speakingId) {
      window.speechSynthesis.cancel();
      setSpeakingId(null);
    }
    setMessages([]);
    setSessionId(null);
    setInput("");
    inputRef.current?.focus();
  };

  const handleSend = async (overridePrompt?: string) => {
    const text = (overridePrompt ?? input).trim();
    if (!text || loading) return;

    const userMsg: Message = {
      id: `usr_${Date.now()}`,
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
      cityName: activeCityName,
    };

    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput("");
    setLoading(true);

    try {
      const res = await api.post<ChatResponse>("/v1/chat", {
        message: text,
        session_id: sessionId,
        city_name: activeCityName,
        city_id: location.id,
        latitude: activeLat,
        longitude: activeLon,
      });

      const assistantMsg: Message = {
        id: `asst_${Date.now()}`,
        role: "assistant",
        content: res.message,
        timestamp: res.timestamp || new Date().toISOString(),
        toolCalls: res.tool_calls,
        toolResults: res.tool_results,
        degraded: res.degraded,
        model: res.model,
        cityName: activeCityName,
      };

      const finalMessages = [...newMessages, assistantMsg];
      setMessages(finalMessages);
      const newSid = res.session_id || sessionId || `sess_${Date.now()}`;
      setSessionId(newSid);
      saveCurrentSession(finalMessages, newSid);
    } catch (err) {
      const errorMsg: Message = {
        id: `err_${Date.now()}`,
        role: "assistant",
        content: `⚠️ Unable to connect to city intelligence services. Please verify backend connectivity. (${String(err)})`,
        timestamp: new Date().toISOString(),
        degraded: true,
        model: "offline-fallback",
        cityName: activeCityName,
      };
      setMessages([...newMessages, errorMsg]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Copy text helper
  const handleCopy = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  // Text to Speech
  const toggleTTS = (id: string, text: string) => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;

    if (speakingId === id) {
      window.speechSynthesis.cancel();
      setSpeakingId(null);
      return;
    }

    window.speechSynthesis.cancel();
    const cleanText = text.replace(/[*#`_•]/g, "").replace(/https?:\/\/\S+/g, "");
    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.rate = 1.05;
    utterance.pitch = 1.0;
    utterance.onend = () => setSpeakingId(null);
    utterance.onerror = () => setSpeakingId(null);

    setSpeakingId(id);
    window.speechSynthesis.speak(utterance);
  };

  // Speech Recognition (Voice Input)
  const toggleVoiceInput = () => {
    if (typeof window === "undefined") return;
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("Speech recognition is not supported in this browser. Please use Chrome or Edge.");
      return;
    }

    if (isRecording) {
      recognitionRef.current?.stop();
      setIsRecording(false);
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = "en-IN";
    recognition.interimResults = true;
    recognition.continuous = false;

    recognition.onstart = () => setIsRecording(true);
    recognition.onresult = (event: any) => {
      const transcript = Array.from(event.results)
        .map((r: any) => r[0].transcript)
        .join("");
      setInput(transcript);
    };
    recognition.onerror = () => setIsRecording(false);
    recognition.onend = () => setIsRecording(false);

    recognitionRef.current = recognition;
    recognition.start();
  };

  // Filtered cities list for city switcher modal
  const filteredCities = INDIA_LOCATIONS.filter((loc) => {
    if (loc.id === "all_india") return false;
    if (!citySearch) return true;
    const q = citySearch.toLowerCase();
    return loc.name.toLowerCase().includes(q) || loc.state.toLowerCase().includes(q) || loc.region.toLowerCase().includes(q);
  });

  return (
    <div className={s.chatContainer}>
      {/* ─── CLAUDE-STYLE SIDEBAR ─── */}
      <aside className={`${s.sidebar} ${sidebarOpen ? s.sidebarVisible : s.sidebarHidden}`}>
        <div className={s.sidebarHeader}>
          <div className={s.brandBadge}>
            <div className={s.brandIcon}>A</div>
            <div className={s.brandInfo}>
              <span className={s.brandTitle}>Auralis AI</span>
              <span className={s.brandModelPill}>Qwen 2.5 1.5B (AP Fine-Tuned)</span>
            </div>
          </div>
          <button className={s.newChatBtn} onClick={startNewChat} title="Start new conversation (Ctrl+K)">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M12 5v14M5 12h14" />
            </svg>
            <span>New Chat</span>
          </button>
        </div>

        {/* Dynamic City Context Picker */}
        <div className={s.citySelectorSection}>
          <span className={s.sectionLabel}>ACTIVE CIVIC CONTEXT</span>
          <button className={s.activeCityCard} onClick={() => setCityModalOpen(true)}>
            <div className={s.cityIconBox}>📍</div>
            <div className={s.cityTextCol}>
              <span className={s.cityNameRow}>{activeCityName}</span>
              <span className={s.cityStateRow}>{location.state} • {location.cad_zone || "Zone 1"}</span>
            </div>
            <span className={s.citySwitchArrow}>⇄</span>
          </button>
        </div>

        {/* Recent Conversations */}
        <div className={s.recentsSection}>
          <span className={s.sectionLabel}>RECENT SESSIONS</span>
          <div className={s.sessionList}>
            {sessions.length === 0 ? (
              <div className={s.emptySessions}>No recent conversations</div>
            ) : (
              sessions.map((sess) => (
                <button
                  key={sess.id}
                  className={`${s.sessionItem} ${sess.id === sessionId ? s.sessionActive : ""}`}
                  onClick={() => {
                    setSessionId(sess.id);
                  }}
                >
                  <span className={s.sessionIcon}>💬</span>
                  <div className={s.sessionMeta}>
                    <span className={s.sessionTitle}>{sess.title}</span>
                    <span className={s.sessionSub}>{sess.cityName} • {sess.messageCount} msgs</span>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        {/* System Guardrail Status */}
        <div className={s.sidebarFooter}>
          <div className={s.statusPill}>
            <span className={s.greenDot} />
            <span>Zero-Fabrication Live Grounding</span>
          </div>
        </div>
      </aside>

      {/* ─── MAIN CHAT VIEWPORT ─── */}
      <main className={s.mainChat}>
        {/* Top Floating Control Bar */}
        <header className={s.topBar}>
          <button className={s.sidebarToggleBtn} onClick={() => setSidebarOpen((v) => !v)} title="Toggle conversation list">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 12h18M3 6h18M3 18h18" />
            </svg>
          </button>

          <div className={s.topBarLocationPill} onClick={() => setCityModalOpen(true)}>
            <span className={s.pinPulse}>📍</span>
            <span className={s.topCityLabel}>{activeCityName}, {location.state}</span>
            <span className={s.changeCityTag}>Change City</span>
          </div>

          <div className={s.topBarRight}>
            <div className={s.modelBadge}>
              <span className={s.modelDot} />
              <span>Auralis-AP-Urban-1.5B (Local)</span>
            </div>
          </div>
        </header>

        {/* Message Thread */}
        <div className={s.messageThread}>
          {messages.length === 0 ? (
            /* Claude-Style Welcome Screen */
            <div className={s.welcomeContainer}>
              <div className={s.welcomeIconRing}>
                <div className={s.welcomeInsignia}>A</div>
              </div>
              <h1 className={s.welcomeTitle}>Good afternoon, Operator.</h1>
              <p className={s.welcomeSubtitle}>
                Connected to verified real-time telemetry and civic operations for <strong>{activeCityName}</strong>.
                Ask any question, scan active hazards, or query municipal documentation.
              </p>

              {/* Bento Suggestion Cards */}
              <div className={s.quickGrid}>
                {quickActions.map((action, idx) => (
                  <button key={idx} className={s.quickCard} onClick={() => handleSend(action.prompt)}>
                    <div className={s.quickEmoji}>{action.emoji}</div>
                    <div className={s.quickTexts}>
                      <span className={s.quickTitle}>{action.title}</span>
                      <span className={s.quickSub}>{action.subtitle}</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            /* Message List */
            <div className={s.messageList}>
              {messages.map((msg) => (
                <div key={msg.id} className={`${s.messageRow} ${msg.role === "user" ? s.rowUser : s.rowAssistant}`}>
                  {msg.role === "assistant" && (
                    <div className={s.assistantAvatar}>
                      <span>A</span>
                    </div>
                  )}

                  <div className={s.messageBubble}>
                    {/* Tool Calls Accordion */}
                    {msg.toolCalls && msg.toolCalls.length > 0 && (
                      <div className={s.toolsBanner}>
                        {msg.toolCalls.map((tc) => (
                          <div key={tc.id} className={s.toolCard}>
                            <button
                              className={s.toolCardHeader}
                              onClick={() => setExpandedToolId(expandedToolId === tc.id ? null : tc.id)}
                            >
                              <span className={s.toolIcon}>⚡</span>
                              <span className={s.toolName}>Executed: <code>{tc.name}</code></span>
                              <span className={s.toolCityTag}>📍 {activeCityName}</span>
                              <span className={s.toolChevron}>{expandedToolId === tc.id ? "▲" : "▼"}</span>
                            </button>
                            {expandedToolId === tc.id && (
                              <div className={s.toolDrawer}>
                                <div className={s.toolDrawerLabel}>Verified Tool Arguments:</div>
                                <pre className={s.toolCode}>{JSON.stringify(tc.arguments, null, 2)}</pre>
                                {msg.toolResults?.find((tr) => tr.tool_use_id === tc.id) && (
                                  <>
                                    <div className={s.toolDrawerLabel}>Raw Telemetry Payload:</div>
                                    <pre className={s.toolCode}>
                                      {JSON.stringify(
                                        msg.toolResults.find((tr) => tr.tool_use_id === tc.id)?.result,
                                        null,
                                        2
                                      )}
                                    </pre>
                                  </>
                                )}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Markdown Message Body */}
                    <div className={s.messageText}>{renderMarkdown(msg.content)}</div>

                    {/* Assistant Message Actions Toolbar */}
                    {msg.role === "assistant" && (
                      <div className={s.messageToolbar}>
                        <span className={s.msgTime}>{formatTime(msg.timestamp)}</span>
                        {msg.model && <span className={s.modelTag}>{msg.model}</span>}

                        <div className={s.actionBtnsGroup}>
                          <button
                            className={s.toolBtn}
                            onClick={() => handleCopy(msg.id, msg.content)}
                            title="Copy text"
                          >
                            {copiedId === msg.id ? "✓ Copied" : "📋 Copy"}
                          </button>

                          <button
                            className={`${s.toolBtn} ${speakingId === msg.id ? s.toolBtnActive : ""}`}
                            onClick={() => toggleTTS(msg.id, msg.content)}
                            title="Read aloud"
                          >
                            {speakingId === msg.id ? (
                              <span className={s.waveContainer}>
                                <span className={s.waveBar} />
                                <span className={s.waveBar} />
                                <span className={s.waveBar} />
                                Stop Audio
                              </span>
                            ) : (
                              "🔊 Read Aloud"
                            )}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {loading && (
                <div className={`${s.messageRow} ${s.rowAssistant}`}>
                  <div className={s.assistantAvatar}>
                    <span>A</span>
                  </div>
                  <div className={`${s.messageBubble} ${s.thinkingBubble}`}>
                    <div className={s.claudeThinking}>
                      <span className={s.thinkingDot} />
                      <span className={s.thinkingDot} />
                      <span className={s.thinkingDot} />
                      <span className={s.thinkingLabel}>Synthesizing live data for {activeCityName}...</span>
                    </div>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* ─── CLAUDE-STYLE FLOATING INPUT DOCK ─── */}
        <div className={s.inputDock}>
          <div className={s.inputWrapper}>
            {/* Input Context Pill */}
            <div className={s.inputContextBar}>
              <div className={s.inputContextTag}>
                <span className={s.contextDot} />
                <span>Context: <strong>{activeCityName}</strong> ({location.state})</span>
              </div>
              <span className={s.groundingLabel}>🔒 Verified Evidence Only</span>
            </div>

            <textarea
              ref={inputRef}
              className={s.textarea}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={`Ask Auralis anything about ${activeCityName} (weather, incidents, traffic, hospitals)...`}
              rows={2}
              disabled={loading}
            />

            <div className={s.inputActionRow}>
              <div className={s.leftActionBtns}>
                <button
                  className={`${s.iconActionBtn} ${isRecording ? s.recordingActive : ""}`}
                  onClick={toggleVoiceInput}
                  title="Voice input (Speech to Text)"
                  type="button"
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                    <line x1="12" y1="19" x2="12" y2="23" />
                    <line x1="8" y1="23" x2="16" y2="23" />
                  </svg>
                  {isRecording && <span className={s.recPulse} />}
                </button>

                <button
                  className={s.iconActionBtn}
                  onClick={() => setCityModalOpen(true)}
                  title="Switch target city"
                  type="button"
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="10" r="3" />
                    <path d="M12 21.7C17.3 17 20 13 20 10a8 8 0 1 0-16 0c0 3 2.7 7 8 11.7z" />
                  </svg>
                </button>
              </div>

              <button
                className={`${s.sendButton} ${input.trim() && !loading ? s.sendButtonActive : ""}`}
                onClick={() => handleSend()}
                disabled={!input.trim() || loading}
                title="Send message (Enter)"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="22" y1="2" x2="11" y2="13" />
                  <polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              </button>
            </div>
          </div>
          <div className={s.inputDisclaimer}>
            Auralis AI synthesizes verified real-time telemetry from Open-Meteo, GloFAS, OpenWeatherMap & municipal feeds.
          </div>
        </div>
      </main>

      {/* ─── CITY SWITCHER MODAL ─── */}
      {cityModalOpen && (
        <div className={s.modalBackdrop} onClick={() => setCityModalOpen(false)}>
          <div className={s.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={s.modalHeader}>
              <div className={s.modalTitleCol}>
                <h3 className={s.modalTitle}>Select Indian City</h3>
                <p className={s.modalSubtitle}>Choose any city to switch live telemetry, hazard scoring & AI context</p>
              </div>
              <button className={s.modalCloseBtn} onClick={() => setCityModalOpen(false)}>✕</button>
            </div>

            <div className={s.searchBox}>
              <span className={s.searchIcon}>🔍</span>
              <input
                type="text"
                className={s.searchInput}
                placeholder="Search city, state or district..."
                value={citySearch}
                onChange={(e) => setCitySearch(e.target.value)}
                autoFocus
              />
            </div>

            <div className={s.cityGridList}>
              {filteredCities.map((loc) => {
                const isSelected = location.id === loc.id;
                return (
                  <button
                    key={loc.id}
                    className={`${s.cityCardOption} ${isSelected ? s.cityCardSelected : ""}`}
                    onClick={() => {
                      setLocation(loc);
                      setCityModalOpen(false);
                    }}
                  >
                    <div className={s.cityCardHeader}>
                      <span className={s.cityCardName}>{loc.name}</span>
                      {isSelected && <span className={s.activeBadge}>Active</span>}
                    </div>
                    <span className={s.cityCardSub}>{loc.state} • {loc.region}</span>
                    <span className={s.cityCoords}>
                      {loc.coordinates[1].toFixed(2)}°N, {loc.coordinates[0].toFixed(2)}°E
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
