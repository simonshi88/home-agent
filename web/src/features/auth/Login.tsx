import { FormEvent, useState } from "react";

export function Login({ onLogin }: { onLogin: (password: string) => Promise<void> }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await onLogin(password);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法登录");
    }
  }

  return <main className="grid min-h-screen place-items-center bg-stone-50 p-5 text-emerald-950">
    <form onSubmit={submit} className="w-full max-w-sm rounded-3xl border border-emerald-100 bg-white p-7 shadow-sm">
      <p className="text-sm font-semibold tracking-widest text-emerald-700">家庭育儿助手</p>
      <h1 className="mt-2 text-3xl font-bold">宝宝记录</h1>
      <p className="mt-3 text-sm leading-6 text-stone-500">输入家庭服务密码，继续记录与查询。</p>
      <label className="mt-6 block text-sm font-semibold">服务密码</label>
      <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" required className="mt-2 w-full rounded-xl border border-stone-200 px-3 py-3 outline-none focus:border-emerald-600" />
      {error && <p className="mt-3 text-sm text-red-700">{error}</p>}
      <button className="mt-5 w-full rounded-xl bg-emerald-700 px-4 py-3 font-semibold text-white hover:bg-emerald-800">进入对话</button>
    </form>
  </main>;
}
