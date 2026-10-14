function trimTrailingSlash(value: string) {
  return value.replace(/\/+$/, "");
}

export const blogConfig = {
  siteUrl: trimTrailingSlash(process.env.SITE_URL || "https://www.example.com"),
  siteName: process.env.SITE_NAME || "Example",
  blogTitle: process.env.BLOG_TITLE || "Блог",
  blogDescription: process.env.BLOG_DESCRIPTION || "Практические статьи, инструкции и разборы.",
  authorName: process.env.BLOG_AUTHOR_NAME || "Редакция",
  authorUrl: process.env.BLOG_AUTHOR_URL || "/about",
  wordpressBaseUrl: trimTrailingSlash(process.env.WORDPRESS_BASE_URL || ""),
  revalidateSeconds: Number(process.env.WORDPRESS_REVALIDATE_SECONDS || "300") || 300,
} as const;

export function absoluteUrl(pathname = "/") {
  const base = blogConfig.siteUrl.replace(/\/+$/, "");
  const cleanPath = pathname.replace(/^\/+/, "");
  return cleanPath ? `${base}/${cleanPath}` : `${base}/`;
}
