import { useEffect, useRef, useState } from "react";
import { AgentResponse, ChatMessage, api } from "./api";

interface ChatPanelProps {
  isOpen: boolean;
  onClose: () => void;
  onDataChanged: () => void;
}

export function ChatPanel({ isOpen, onClose, onDataChanged }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content:
        "Hi! I'm your staffing assistant. Tell me what assignments to make — for example:\n• "Assign Yunxuan 25% on Nucor"\n• "Remove Josh from Cargill PSO CoE"\n• "Set Nancy at 50% on Signature Aviation for the next 4 weeks"",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: ChatMessage = { role: "user", content: text };
    const nextMessages = [...messages, userMsg];
    setMessages(nextMessages);
    setInput("");
    setLoading(true);

    try {
      // Only send the non-greeting history to the backend
      const history = nextMessages.filter((m) => !(m.role === "assistant" && nextMessages.indexOf(m) === 0));
      const response: AgentResponse = await api.sendAgentMessage(history);
      setMessages([...nextMessages, { role: "assistant", content: response.reply }]);
      if (response.data_changed) {
        onDataChanged();
      }
    } catch (err) {
      setMessages([
        ...nextMessages,
        {
          role: "assistant",
          content: "Sorry, something went wrong: " + (err instanceof Error ? err.message : "Unknown error"),
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

  return (
    <div className={`chat-panel${isOpen ? " open" : ""}`}>
      <div className="chat-panel__header">
        <span>Staffing Assistant</span>
        <button className="chat-panel__close" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>

      <div className="chat-panel__messages">
        {messages.map((msg, idx) => (
          <div key={idx} className={`chat-message ${msg.role}`}>
            {msg.content}
          </div>
        ))}
        {loading && (
          <div className="chat-message assistant thinking">Thinking…</div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="chat-panel__input-row">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="e.g. Assign Yunxuan 25% on Nucor"
          rows={2}
          disabled={loading}
        />
        <button className="chat-panel__send" onClick={handleSend} disabled={loading || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
