"use client";

/**
 * Auralis AI — /chat
 *
 * Conversational surface over the city services. Answers are grounded in the
 * tool results shown alongside them; every tool call stays inspectable.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useShell } from "@/components/shell/ShellState";
import { Icon, type IconName } from "@/components/ui/Icon";
import { getSuggestedCity, rankedSearch, recommendedLocations } from "@/lib/locations";
import { locateUser, sourceLabel } from "@/lib/geolocate";
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
  messages: Message[];
}

const SESSIONS_KEY = "auralis_chat_sessions";

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

/**
 * Minimal markdown for the shapes the model actually emits: headings,
 * bullets, paragraphs, bold and inline code. Runs of blank lines collapse —
 * left in, they compound with the paragraph spacing and tear the answer apart.
 */
function renderMarkdown(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];

  for (const [i, line] of text.split("\n").entries()) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    if (trimmed.startsWith("### ")) {
      nodes.push(
        <h4 key={i} className={s.mdH3}>
          {trimmed.slice(4)}
        </h4>
      );
      continue;
    }

    if (trimmed.startsWith("## ")) {
      nodes.push(
        <h3 key={i} className={s.mdH2}>
          {trimmed.slice(3)}
        </h3>
      );
      continue;
    }

    if (/^[•\-*]\s+/.test(trimmed)) {
      nodes.push(
        <div key={i} className={s.mdListItem}>
          <span className={s.bulletPoint} aria-hidden="true">
            •
          </span>
          <span>{renderInline(trimmed.replace(/^[•\-*]\s+/, ""), i)}</span>
        </div>
      );
      continue;
    }

    nodes.push(
      <p key={i} className={s.mdP}>
        {renderInline(trimmed, i)}
      </p>
    );
  }

  return nodes;
}

function renderInline(text: string, lineIdx: number): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  // Bold before italic, or `**x**` is eaten as two empty italics. The source
  // and provenance lines are emitted in italics, so without this the answer
  // showed raw asterisks around them.
  const regex = /(\*\*(.+?)\*\*|`(.+?)`|\*([^*]+?)\*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index));
    if (match[2]) {
      parts.push(
        <strong key={`b-${lineIdx}-${match.index}`} className={s.boldText}>
          {match[2]}
        </strong>
      );
    } else if (match[3]) {
      parts.push(
        <code key={`c-${lineIdx}-${match.index}`} className={s.codePill}>
          {match[3]}
        </code>
      );
    } else if (match[4]) {
      parts.push(
        <em key={`i-${lineIdx}-${match.index}`} className={s.sourceNote}>
          {match[4]}
        </em>
      );
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts.length > 0 ? parts : [text];
}

export default function ChatPage() {
  const { location, setLocation, queryCoords, setPreciseCoords } = useShell();
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
  const [greeting, setGreeting] = useState("Hello");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [locateMsg, setLocateMsg] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const recognitionRef = useRef<any>(null);

  const activeCityName =
    location.id === "all_india" ? "National" : location.name.split("/")[0].trim();
  // The device fix when geolocation gave us one, else the city centroid. A
  // centroid can be kilometres from the user, which changes which hospital is
  // nearest and which corridor is theirs.
  const activeLat = queryCoords.lat;
  const activeLon = queryCoords.lon;

  const quickActions: { icon: IconName; label: string; prompt: string }[] = [
    {
      icon: "forecast",
      label: "Weather right now",
      prompt: `What's the current verified weather in ${activeCityName}?`,
    },
    {
      icon: "critical",
      label: "Open incidents",
      prompt: `Are there any active civic incidents or hazard advisories in ${activeCityName}?`,
    },
    {
      icon: "shield",
      label: "Nearest hospitals",
      prompt: `Find nearest hospitals and emergency medical centres in ${activeCityName}`,
    },
    {
      icon: "map",
      label: "Traffic and safe routes",
      prompt: `What is the traffic congestion status and safe corridor in ${activeCityName}?`,
    },
  ];

  // Greeting is set after mount: the server and the browser can sit in
  // different hours, and a mismatch here would break hydration.
  useEffect(() => {
    const h = new Date().getHours();
    setGreeting(h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening");
  }, []);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading, scrollToBottom]);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(SESSIONS_KEY);
      if (saved) setSessions(JSON.parse(saved));
    } catch {
      // A corrupt or unavailable store just means no history to offer.
    }
  }, []);

  const saveCurrentSession = useCallback(
    (newMessages: Message[], sid: string) => {
      if (newMessages.length === 0) return;
      const firstUserMsg = newMessages.find((m) => m.role === "user");
      const title = firstUserMsg
        ? firstUserMsg.content.slice(0, 40) + (firstUserMsg.content.length > 40 ? "…" : "")
        : "Untitled";

      setSessions((prev) => {
        const next: Session[] = [
          {
            id: sid,
            title,
            cityName: activeCityName,
            lastActive: new Date().toISOString(),
            messages: newMessages,
          },
          ...prev.filter((x) => x.id !== sid),
        ].slice(0, 20);
        try {
          localStorage.setItem(SESSIONS_KEY, JSON.stringify(next));
        } catch {
          // Over quota: history is a convenience, not a guarantee.
        }
        return next;
      });
    },
    [activeCityName]
  );

  const stopSpeech = () => {
    if (speakingId) {
      window.speechSynthesis.cancel();
      setSpeakingId(null);
    }
  };

  const startNewChat = () => {
    stopSpeech();
    setMessages([]);
    setSessionId(null);
    setInput("");
    inputRef.current?.focus();
  };

  const openSession = (sess: Session) => {
    stopSpeech();
    setSessionId(sess.id);
    setMessages(sess.messages ?? []);
  };

  const useMyLocation = async () => {
    setLocating(true);
    setLocateMsg(null);
    const r = await locateUser();
    setLocating(false);

    if (r.status !== "ok" || !r.coords || !r.match) {
      setLocateMsg(
        r.permissionDenied
          ? "Location is blocked for this site. Allow it from the address-bar icon (and Brave Shields), then retry."
          : "No location source answered. Search for the city instead."
      );
      return;
    }
    if (!r.match.insideCoverage) {
      // Still useful: name the closest covered city rather than refusing flatly.
      setLocateMsg(
        `Your network places you ~${r.match.distanceKm.toFixed(0)} km outside coverage. Closest covered city is ${r.match.location.name}.`
      );
      return;
    }
    setLocation(r.match.location);
    setPreciseCoords({ lat: r.coords.lat, lon: r.coords.lon, accuracyM: r.accuracyM ?? 0 });
    setCityModalOpen(false);
    setCitySearch("");
  };

  const deleteSession = (id: string) => {
    setConfirmDeleteId(null);
    setSessions((prev) => {
      const next = prev.filter((x) => x.id !== id);
      try {
        localStorage.setItem(SESSIONS_KEY, JSON.stringify(next));
      } catch {
        // Nothing to do: the list on screen is already correct.
      }
      return next;
    });
    // Deleting the conversation you are reading empties the thread with it.
    if (id === sessionId) {
      stopSpeech();
      setSessionId(null);
      setMessages([]);
    }
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
    if (inputRef.current) inputRef.current.style.height = "auto";
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
      setMessages([
        ...newMessages,
        {
          id: `err_${Date.now()}`,
          role: "assistant",
          content: `Could not reach the city services. ${String(err)}`,
          timestamp: new Date().toISOString(),
          degraded: true,
          model: "offline",
          cityName: activeCityName,
        },
      ]);
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

  /** Grow with the content up to the max-height the stylesheet sets. */
  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = `${e.target.scrollHeight}px`;
  };

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const toggleTTS = (id: string, text: string) => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;

    if (speakingId === id) {
      stopSpeech();
      return;
    }

    window.speechSynthesis.cancel();
    const clean = text.replace(/[*#`_•]/g, "").replace(/https?:\/\/\S+/g, "");
    const utterance = new SpeechSynthesisUtterance(clean);
    utterance.rate = 1.05;
    utterance.onend = () => setSpeakingId(null);
    utterance.onerror = () => setSpeakingId(null);

    setSpeakingId(id);
    window.speechSynthesis.speak(utterance);
  };

  const toggleVoiceInput = () => {
    if (typeof window === "undefined") return;
    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) return;

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
      setInput(
        Array.from(event.results)
          .map((r: any) => r[0].transcript)
          .join("")
      );
    };
    recognition.onerror = () => setIsRecording(false);
    recognition.onend = () => setIsRecording(false);

    recognitionRef.current = recognition;
    recognition.start();
  };

  // Ranked, not filtered: typing "guntur" should put Guntur first, and an
  // empty box should suggest somewhere useful rather than the alphabet.
  const filteredCities = citySearch.trim()
    ? rankedSearch(citySearch, 40).map((r) => r.location)
    : recommendedLocations(location, 40);

  const suggestion = getSuggestedCity(citySearch);

  return (
    <div className={s.chatContainer}>
      <aside className={`${s.sidebar} ${sidebarOpen ? "" : s.sidebarHidden}`}>
        <div className={s.sidebarHeader}>
          <div className={s.brandBadge}>
            <img className={s.brandIcon} src="/logo.svg" alt="" aria-hidden="true" />
            <span className={s.brandTitle}>Auralis</span>
          </div>
        </div>

        <button className={s.newChatBtn} onClick={startNewChat}>
          <Icon name="plus" size={14} />
          <span>New chat</span>
        </button>

        <div className={s.citySelectorSection}>
          <span className={s.sectionLabel}>City</span>
          <button className={s.activeCityCard} onClick={() => setCityModalOpen(true)}>
            <span className={s.cityIconBox}>
              <Icon name="map" size={14} />
            </span>
            <span className={s.cityTextCol}>
              <span className={s.cityNameRow}>{activeCityName}</span>
              <span className={s.cityStateRow}>{location.district} district</span>
            </span>
            <span className={s.citySwitchArrow}>
              <Icon name="chevronRight" size={14} />
            </span>
          </button>
        </div>

        <div className={s.recentsSection}>
          <span className={s.sectionLabel}>Recent</span>
          <div className={s.sessionList}>
            {sessions.length === 0 ? (
              <p className={s.emptySessions}>Nothing here yet.</p>
            ) : (
              sessions.map((sess) => (
                <div
                  key={sess.id}
                  className={`${s.sessionRow} ${sess.id === sessionId ? s.sessionActive : ""}`}
                >
                  <button className={s.sessionItem} onClick={() => openSession(sess)}>
                    <span className={s.sessionTitle}>{sess.title}</span>
                    <span className={s.sessionSub}>{sess.cityName}</span>
                  </button>
                  {confirmDeleteId === sess.id ? (
                    <span className={s.confirmDelete}>
                      <button
                        className={s.confirmYes}
                        onClick={() => deleteSession(sess.id)}
                        aria-label={`Confirm delete: ${sess.title}`}
                      >
                        Delete
                      </button>
                      <button
                        className={s.confirmNo}
                        onClick={() => setConfirmDeleteId(null)}
                        aria-label="Cancel delete"
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      className={s.sessionDelete}
                      onClick={() => setConfirmDeleteId(sess.id)}
                      aria-label={`Delete chat: ${sess.title}`}
                    >
                      <Icon name="trash" size={13} />
                    </button>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </aside>

      <main className={s.mainChat}>
        <header className={s.topBar}>
          <button
            className={s.sidebarToggleBtn}
            onClick={() => setSidebarOpen((v) => !v)}
            aria-label={sidebarOpen ? "Hide conversations" : "Show conversations"}
          >
            <Icon name="menu" size={18} />
          </button>

          <button className={s.topBarLocationPill} onClick={() => setCityModalOpen(true)}>
            <Icon name="map" size={14} />
            <span>{activeCityName}</span>
            <Icon name="chevronDown" size={14} />
          </button>
        </header>

        <div className={s.messageThread}>
          {messages.length === 0 ? (
            <div className={s.welcomeContainer}>
              <h1 className={s.welcomeTitle}>{greeting}.</h1>
              <p className={s.welcomeSubtitle}>Ask about {activeCityName}.</p>

              <div className={s.quickGrid}>
                {quickActions.map((action) => (
                  <button
                    key={action.label}
                    className={s.quickCard}
                    onClick={() => handleSend(action.prompt)}
                  >
                    <Icon name={action.icon} size={16} />
                    <span>{action.label}</span>
                    <span className={s.quickArrow}>
                      <Icon name="arrowRight" size={14} />
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className={s.messageList}>
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`${s.messageRow} ${msg.role === "user" ? s.rowUser : s.rowAssistant}`}
                >
                  {msg.role === "assistant" && (
                    <img className={s.assistantAvatar} src="/logo.svg" alt="" aria-hidden="true" />
                  )}

                  <div className={s.messageBubble}>
                    <div className={s.messageText}>{renderMarkdown(msg.content)}</div>

                    {msg.role === "assistant" && (
                      <div className={s.messageToolbar}>
                        <span className={s.msgTime}>{formatTime(msg.timestamp)}</span>

                        <div className={s.actionBtnsGroup}>
                          <button
                            className={s.toolBtn}
                            onClick={() => handleCopy(msg.id, msg.content)}
                          >
                            <Icon name={copiedId === msg.id ? "check" : "copy"} size={12} />
                            {copiedId === msg.id ? "Copied" : "Copy"}
                          </button>

                          <button
                            className={`${s.toolBtn} ${speakingId === msg.id ? s.toolBtnActive : ""}`}
                            onClick={() => toggleTTS(msg.id, msg.content)}
                          >
                            <Icon name={speakingId === msg.id ? "close" : "activity"} size={12} />
                            {speakingId === msg.id ? "Stop" : "Read aloud"}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {loading && (
                <div className={`${s.messageRow} ${s.rowAssistant}`}>
                  <img className={s.assistantAvatar} src="/logo.svg" alt="" aria-hidden="true" />
                  <div className={s.messageBubble}>
                    <div className={s.claudeThinking} role="status">
                      <span className={s.thinkingDot} />
                      <span className={s.thinkingDot} />
                      <span className={s.thinkingDot} />
                    </div>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        <div className={s.inputDock}>
          <div className={s.inputWrapper}>
            <textarea
              ref={inputRef}
              className={s.textarea}
              value={input}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              placeholder={`Ask about ${activeCityName}…`}
              rows={1}
              disabled={loading}
            />

            <div className={s.inputActionRow}>
              <div className={s.leftActionBtns}>
                <button
                  className={`${s.iconActionBtn} ${isRecording ? s.recordingActive : ""}`}
                  onClick={toggleVoiceInput}
                  aria-label={isRecording ? "Stop dictation" : "Dictate"}
                  type="button"
                >
                  <svg
                    width="17"
                    height="17"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                    <line x1="12" y1="19" x2="12" y2="23" />
                  </svg>
                </button>
              </div>

              <button
                className={`${s.sendButton} ${input.trim() && !loading ? s.sendButtonActive : ""}`}
                onClick={() => handleSend()}
                disabled={!input.trim() || loading}
                aria-label="Send"
              >
                <Icon name="arrowRight" size={16} />
              </button>
            </div>
          </div>
        </div>
      </main>

      {cityModalOpen && (
        <div className={s.modalBackdrop} onClick={() => setCityModalOpen(false)}>
          <div className={s.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={s.modalHeader}>
              <h2 className={s.modalTitle}>Change city</h2>
              <button
                className={s.modalCloseBtn}
                onClick={() => setCityModalOpen(false)}
                aria-label="Close"
              >
                <Icon name="close" size={16} />
              </button>
            </div>

            <div className={s.modalSearchBox}>
              <button
                type="button"
                className={s.useLocationBtn}
                onClick={() => void useMyLocation()}
                disabled={locating}
              >
                <Icon name="map" size={15} />
                {locating ? "Locating…" : "Use my location"}
              </button>
              {locateMsg && <p className={s.locateMsg}>{locateMsg}</p>}
              <input
                type="text"
                className={s.modalInput}
                placeholder="Search Andhra Pradesh"
                value={citySearch}
                onChange={(e) => setCitySearch(e.target.value)}
                autoFocus
              />
            </div>

            {suggestion && (
              <div className={s.modalDidYouMean}>
                <span>
                  Did you mean <strong>{suggestion.name}</strong>?
                </span>
                <button
                  type="button"
                  className={s.modalDidYouMeanBtn}
                  onClick={() => {
                    setLocation(suggestion);
                    setCityModalOpen(false);
                    setCitySearch("");
                  }}
                >
                  Use it
                </button>
              </div>
            )}

            <div className={s.modalCityList}>
              {filteredCities.length === 0 ? (
                <p className={s.modalEmpty}>No match for “{citySearch}”.</p>
              ) : (
                filteredCities.map((loc) => (
                  <button
                    key={loc.id}
                    className={`${s.modalCityItem} ${
                      location.id === loc.id ? s.modalCityActive : ""
                    }`}
                    onClick={() => {
                      setLocation(loc);
                      setCityModalOpen(false);
                    }}
                  >
                    <span className={s.modalCityName}>{loc.name}</span>
                    <span className={s.modalCityDistrict}>{loc.district}</span>
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
