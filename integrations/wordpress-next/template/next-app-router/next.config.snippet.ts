// Merge the returned pattern into the host images.remotePatterns if using next/image.
export function wordpressImagePattern() {
  const value = process.env.WORDPRESS_BASE_URL?.replace(/\/+$/, "");
  if (!value) return null;
  const url = new URL(value);
  if (url.protocol !== "https:") return null;
  return { protocol: "https" as const, hostname: url.hostname };
}
