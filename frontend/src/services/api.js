const API_ROOT = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
const TOKEN_KEY = "land_harmonizer_access_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function saveSession(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem("land_harmonizer_user", JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem("land_harmonizer_user");
}

export async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_ROOT}${path}`, { ...options, headers });
  const payload = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) clearSession();
    throw new Error(payload?.detail || `Request failed (${response.status})`);
  }
  return payload;
}

export function uploadFiles({ files, sourceName, onProgress }) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    const form = new FormData();
    form.append("source_name", sourceName);
    for (const file of files) form.append("files", file);
    request.open("POST", `${API_ROOT}/api/v1/ingestion/uploads`);
    const token = getToken();
    if (token) request.setRequestHeader("Authorization", `Bearer ${token}`);
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    });
    request.addEventListener("load", () => {
      const payload = JSON.parse(request.responseText || "null");
      if (request.status >= 200 && request.status < 300) resolve(payload);
      else reject(new Error(payload?.detail || `Upload failed (${request.status})`));
    });
    request.addEventListener("error", () => reject(new Error("Could not connect to the API.")));
    request.send(form);
  });
}

export async function downloadReport(path, filename) {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_ROOT}${path}`, { headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail || `Report download failed (${response.status})`);
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

export { API_ROOT };
