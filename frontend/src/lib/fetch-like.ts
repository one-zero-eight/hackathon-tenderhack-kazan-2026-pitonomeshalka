/** Minimal injectable fetch signature shared by the HTTP clients. */
export type FetchLike = (url: string, init?: RequestInit) => Promise<Response>
