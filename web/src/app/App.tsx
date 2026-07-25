import { useEffect, useState } from "react";
import { Login } from "../features/auth/Login";
import { Chat } from "../features/chat/Chat";
import { api } from "../lib/api";

export default function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [ownerId, setOwnerId] = useState<string | null>(null);

  useEffect(() => {
    api.session()
      .then((session) => {
        setOwnerId(session.owner_id);
        setAuthenticated(true);
      })
      .catch(() => setAuthenticated(false));
  }, []);

  if (authenticated === null) return <main className="grid min-h-screen place-items-center bg-stone-50 text-stone-500">正在连接…</main>;
  if (!authenticated) return <Login onLogin={async (password) => {
    await api.login(password);
    const session = await api.session();
    setOwnerId(session.owner_id);
    setAuthenticated(true);
  }} />;
  if (!ownerId) return <main className="grid min-h-screen place-items-center bg-stone-50 text-stone-500">正在连接…</main>;

  return <Chat key={ownerId} ownerId={ownerId} onLogout={async () => {
    await api.logout();
    setOwnerId(null);
    setAuthenticated(false);
  }} />;
}
