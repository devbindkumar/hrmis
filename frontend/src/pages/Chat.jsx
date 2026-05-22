import { useEffect, useRef, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Send, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";

const PRESENCE_COLOR = {
  present: "bg-emerald-500",
  active: "bg-emerald-500",
  remote: "bg-blue-500",
  in_meeting: "bg-fuchsia-500",
  on_break: "bg-slate-400",
  on_leave: "bg-amber-500",
  offline: "bg-slate-300",
};

export default function Chat() {
  const [contacts, setContacts] = useState([]);
  const [active, setActive] = useState(null);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [filter, setFilter] = useState("");
  const scrollRef = useRef();

  const loadContacts = async () => {
    const { data } = await api.get("/chat/contacts");
    setContacts(data);
    if (!active && data.length) setActive(data[0]);
  };

  useEffect(() => { loadContacts(); /* eslint-disable-next-line */ }, []);

  useEffect(() => {
    if (!active) return;
    const load = async () => {
      const { data } = await api.get(`/chat/messages/${active.user_id}`);
      setMessages(data);
      setTimeout(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, 10);
    };
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [active?.user_id]);

  const send = async (e) => {
    e?.preventDefault();
    if (!text.trim() || !active) return;
    try {
      const { data } = await api.post("/chat/send", { to_user_id: active.user_id, body: text });
      setMessages([...messages, data]);
      setText("");
      setTimeout(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, 10);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const filtered = contacts.filter((c) => !filter || c.name.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="p-4 md:p-6 animate-fade-up" data-testid="chat-page">
      <div className="surface overflow-hidden flex flex-col md:flex-row h-[calc(100vh-160px)] min-h-[520px]">
        {/* contacts */}
        <div className="md:w-80 border-b md:border-b-0 md:border-r border-slate-100 flex flex-col">
          <div className="p-4 border-b border-slate-100">
            <h2 className="font-display text-lg font-semibold text-slate-900">Messages</h2>
            <div className="mt-3 relative">
              <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" strokeWidth={1.5} />
              <Input value={filter} onChange={(e)=>setFilter(e.target.value)} placeholder="Find a teammate" className="pl-9 h-9 rounded-lg border-slate-200" data-testid="chat-search" />
            </div>
          </div>
          <div className="flex-1 overflow-y-auto chat-scroll">
            {filtered.length === 0 ? <div className="p-6 text-sm text-slate-400">No teammates.</div> :
              filtered.map((c) => (
                <button
                  key={c.user_id}
                  onClick={()=>setActive(c)}
                  className={`w-full text-left flex items-center gap-3 px-4 py-3 hover:bg-slate-50 border-b border-slate-50 ${active?.user_id === c.user_id ? "bg-slate-50" : ""}`}
                  data-testid={`chat-contact-${c.user_id}`}
                >
                  <div className="relative">
                    <Avatar className="h-10 w-10">
                      <AvatarImage src={c.avatar_url} alt={c.name} />
                      <AvatarFallback className="text-xs bg-slate-100">{c.name.split(" ").map(p=>p[0]).slice(0,2).join("")}</AvatarFallback>
                    </Avatar>
                    <span className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full ring-2 ring-white ${PRESENCE_COLOR[c.presence] || PRESENCE_COLOR.offline}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <div className="text-sm font-medium text-slate-900 truncate">{c.name}</div>
                      {c.unread > 0 && <span className="text-[10px] h-4 min-w-4 px-1 rounded-full bg-blue-600 text-white font-medium grid place-items-center">{c.unread}</span>}
                    </div>
                    <div className="text-xs text-slate-500 truncate">{c.last_message || c.designation}</div>
                  </div>
                </button>
              ))}
          </div>
        </div>

        {/* chat window */}
        <div className="flex-1 flex flex-col min-w-0">
          {active ? (
            <>
              <div className="p-4 border-b border-slate-100 flex items-center gap-3">
                <div className="relative">
                  <Avatar className="h-9 w-9"><AvatarImage src={active.avatar_url} /><AvatarFallback>{active.name.split(" ").map(p=>p[0]).slice(0,2).join("")}</AvatarFallback></Avatar>
                  <span className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full ring-2 ring-white ${PRESENCE_COLOR[active.presence] || PRESENCE_COLOR.offline}`} />
                </div>
                <div>
                  <div className="text-sm font-medium text-slate-900">{active.name}</div>
                  <div className="text-xs text-slate-500 capitalize">{(active.presence || 'offline').replace('_', ' ')} · {active.designation}</div>
                </div>
              </div>

              <div ref={scrollRef} className="flex-1 overflow-y-auto chat-scroll p-5 bg-slate-50/40 space-y-3" data-testid="chat-thread">
                {messages.length === 0 ? <div className="text-center text-sm text-slate-400 mt-12">Say hi to {active.name.split(" ")[0]}.</div> :
                  messages.map((m, i) => {
                    const mine = m.from_user_id !== active.user_id;
                    return (
                      <div key={m.id || i} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
                        <div className={`max-w-[75%] px-3.5 py-2 rounded-2xl text-sm ${mine ? "bg-slate-900 text-white rounded-br-md" : "bg-white border border-slate-100 text-slate-800 rounded-bl-md"}`}>
                          {m.body}
                          <div className={`text-[10px] mt-1 ${mine ? "text-slate-300" : "text-slate-400"}`}>{new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
                        </div>
                      </div>
                    );
                  })}
              </div>

              <form onSubmit={send} className="p-3 border-t border-slate-100 flex items-center gap-2">
                <Input value={text} onChange={(e)=>setText(e.target.value)} placeholder={`Message ${active.name.split(" ")[0]}…`} className="h-11 rounded-lg border-slate-200" data-testid="chat-input" />
                <button type="submit" className="h-11 w-11 rounded-lg bg-slate-900 hover:bg-slate-800 text-white grid place-items-center" data-testid="chat-send-btn">
                  <Send className="h-4 w-4" strokeWidth={1.5} />
                </button>
              </form>
            </>
          ) : (
            <div className="flex-1 grid place-items-center text-sm text-slate-400">Pick a teammate to start chatting.</div>
          )}
        </div>
      </div>
    </div>
  );
}
