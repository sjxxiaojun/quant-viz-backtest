import axios, { type AxiosRequestConfig } from 'axios';

export const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '');

export const apiClient = axios.create({
  baseURL: API_BASE || undefined,
});

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const payload = error.response?.data;
    if (payload && typeof payload === 'object' && 'detail' in payload) {
      return String(payload.detail || fallback);
    }
    return error.message || fallback;
  }
  return error instanceof Error ? error.message || fallback : fallback;
}

export function getApiErrorPayload(error: unknown): unknown {
  return axios.isAxiosError(error) ? error.response?.data : null;
}

export function isRequestCanceled(error: unknown): boolean {
  return axios.isCancel(error) || (axios.isAxiosError(error) && error.code === 'ERR_CANCELED');
}

export async function apiGet<T>(path: string, config: AxiosRequestConfig = {}): Promise<T> {
  const response = await apiClient.get<T>(path, config);
  return response.data;
}

export async function apiPost<T>(path: string, body?: unknown, config: AxiosRequestConfig = {}): Promise<T> {
  const response = await apiClient.post<T>(path, body, config);
  return response.data;
}
