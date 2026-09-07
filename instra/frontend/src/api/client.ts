/** 统一 API client：错误信息直接取自后端 {ok:false,error}。 */

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init);
  if (!resp.ok) {
    let message = `HTTP ${resp.status}`;
    try {
      const data = await resp.json();
      if (data?.error) message = data.error;
    } catch { /* 忽略非 JSON 错误体 */ }
    throw new Error(message);
  }
  return resp.json() as Promise<T>;
}

/** POST 触发文件下载；失败时抛后端 error。 */
export async function downloadFile(path: string, body: unknown): Promise<void> {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let message = `HTTP ${resp.status}`;
    try {
      const data = await resp.json();
      if (data?.error) message = data.error;
    } catch { /* 忽略 */ }
    throw new Error(message);
  }
  const blob = await resp.blob();
  const disposition = resp.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename\*?=(?:UTF-8''|")?([^";]+)/i);
  const filename = match ? decodeURIComponent(match[1].replace(/"$/, "")) : "export";
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
