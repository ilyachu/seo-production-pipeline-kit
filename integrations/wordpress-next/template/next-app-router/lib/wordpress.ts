import { blogConfig } from "@/config/blog";

export type FeedStatus = "ready" | "missing-config" | "error";
export type Rendered = { rendered: string };
export type YoastHead = {
  title?: string;
  description?: string;
  canonical?: string;
  og_title?: string;
  og_description?: string;
  og_url?: string;
  article_published_time?: string;
};
export type WordPressAuthor = { id: number; name: string; link: string };
export type WordPressMedia = { id: number; alt_text: string; source_url: string };
export type WordPressTerm = { id: number; count?: number; name: string; slug: string; taxonomy?: "category" | "post_tag" };
export type WordPressPost = {
  id: number;
  date: string;
  modified: string;
  slug: string;
  link: string;
  title: Rendered;
  excerpt: Rendered;
  content: Rendered;
  categories: number[];
  tags: number[];
  author: number;
  featured_media: number;
  yoast_head_json?: YoastHead;
  _embedded?: {
    author?: WordPressAuthor[];
    "wp:featuredmedia"?: WordPressMedia[];
    "wp:term"?: WordPressTerm[][];
  };
};
export type PostsPage = { posts: WordPressPost[]; total: number; totalPages: number; status: FeedStatus };

const apiBase = blogConfig.wordpressBaseUrl ? `${blogConfig.wordpressBaseUrl}/wp-json/wp/v2` : "";

function buildUrl(route: string, params?: URLSearchParams) {
  const url = new URL(`${apiBase}${route.startsWith("/") ? route : `/${route}`}`);
  if (params) url.search = params.toString();
  return url.toString();
}

async function fetchWordPress<T>(route: string, params?: URLSearchParams) {
  if (!apiBase) return { data: null, headers: null, status: "missing-config" as const };
  try {
    const response = await fetch(buildUrl(route, params), { next: { revalidate: blogConfig.revalidateSeconds } });
    if (!response.ok) return { data: null, headers: response.headers, status: "error" as const };
    return { data: (await response.json()) as T, headers: response.headers, status: "ready" as const };
  } catch {
    return { data: null, headers: null, status: "error" as const };
  }
}

export async function getCategories() {
  if (!apiBase) return [] as WordPressTerm[];
  const params = new URLSearchParams({ per_page: "100", hide_empty: "true", orderby: "count", order: "desc" });
  const result = await fetchWordPress<WordPressTerm[]>("/categories", params);
  return result.data ?? [];
}

export async function getCategoryBySlug(slug: string) {
  if (!apiBase) return { category: null, status: "missing-config" as const };
  const result = await fetchWordPress<WordPressTerm[]>("/categories", new URLSearchParams({ slug, per_page: "1" }));
  return { category: result.data?.[0] ?? null, status: result.status };
}

export async function getPostsPage(options: { categorySlug?: string; page?: number; perPage?: number } = {}) {
  if (!apiBase) return { posts: [], total: 0, totalPages: 0, status: "missing-config" } satisfies PostsPage;
  const params = new URLSearchParams({
    _embed: "true",
    page: String(options.page ?? 1),
    per_page: String(options.perPage ?? 9),
    status: "publish",
  });
  if (options.categorySlug) {
    const categoryResult = await getCategoryBySlug(options.categorySlug);
    if (categoryResult.status !== "ready") return { posts: [], total: 0, totalPages: 0, status: categoryResult.status } satisfies PostsPage;
    const category = categoryResult.category;
    if (!category) return { posts: [], total: 0, totalPages: 0, status: "ready" } satisfies PostsPage;
    params.set("categories", String(category.id));
  }
  const result = await fetchWordPress<WordPressPost[]>("/posts", params);
  return {
    posts: result.data ?? [],
    total: Number(result.headers?.get("x-wp-total") ?? "0"),
    totalPages: Number(result.headers?.get("x-wp-totalpages") ?? "0"),
    status: result.status,
  } satisfies PostsPage;
}

export async function getPostBySlug(slug: string) {
  if (!apiBase) return { post: null, status: "missing-config" as const };
  const params = new URLSearchParams({ _embed: "true", slug, status: "publish", per_page: "1" });
  const result = await fetchWordPress<WordPressPost[]>("/posts", params);
  return { post: result.data?.[0] ?? null, status: result.status };
}

export async function getRelatedPosts(post: WordPressPost, limit = 3) {
  if (!apiBase) return [];
  const params = new URLSearchParams({ _embed: "true", per_page: String(limit), exclude: String(post.id), status: "publish" });
  if (post.categories[0]) params.set("categories", String(post.categories[0]));
  const result = await fetchWordPress<WordPressPost[]>("/posts", params);
  return result.data ?? [];
}

export async function getAllPostSlugs() {
  const first = await getPostsPage({ page: 1, perPage: 100 });
  if (first.status !== "ready") return [];
  const slugs = first.posts.map((post) => post.slug);
  for (let page = 2; page <= first.totalPages; page += 1) {
    const next = await getPostsPage({ page, perPage: 100 });
    slugs.push(...next.posts.map((post) => post.slug));
  }
  return slugs;
}

export async function getAllPostSitemapEntries() {
  const first = await getPostsPage({ page: 1, perPage: 100 });
  if (first.status !== "ready") return [];
  const posts = [...first.posts];
  for (let page = 2; page <= first.totalPages; page += 1) {
    const next = await getPostsPage({ page, perPage: 100 });
    if (next.status !== "ready") return [];
    posts.push(...next.posts);
  }
  return posts.map((post) => ({ slug: post.slug, modified: post.modified }));
}

export async function getAllCategorySlugs() {
  return (await getCategories()).map((category) => category.slug);
}

export function stripHtml(html = "") {
  return html
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#039;/g, "'")
    .replace(/&laquo;/g, "«")
    .replace(/&raquo;/g, "»")
    .replace(/&mdash;|&#8212;/g, "—")
    .replace(/&ndash;|&#8211;/g, "–")
    .replace(/&hellip;|&#8230;/g, "…")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
}

export function getPostImage(post: WordPressPost) {
  return post._embedded?.["wp:featuredmedia"]?.[0] ?? null;
}

export function getPostAuthor(post: WordPressPost) {
  return post._embedded?.author?.[0] ?? null;
}

export function getPostCategories(post: WordPressPost) {
  return (post._embedded?.["wp:term"]?.flat() ?? []).filter((term) => term.taxonomy === "category" || term.taxonomy === undefined);
}

export function getReadingTime(post: WordPressPost) {
  const count = stripHtml(post.content.rendered).split(/\s+/).filter(Boolean).length;
  return `${Math.max(1, Math.ceil(count / 200))} мин чтения`;
}

export function getSeoTitle(post: WordPressPost) {
  return post.yoast_head_json?.title || stripHtml(post.title.rendered);
}

export function getSeoDescription(post: WordPressPost) {
  return post.yoast_head_json?.description || stripHtml(post.excerpt.rendered);
}
