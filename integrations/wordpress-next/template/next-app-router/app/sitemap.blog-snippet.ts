// Merge this into the host app/sitemap.ts; do not replace existing routes.
import { absoluteUrl } from "@/config/blog";
import { getAllCategorySlugs, getAllPostSitemapEntries } from "@/lib/wordpress";

export async function getBlogSitemapEntries() {
  const [posts, categories] = await Promise.all([getAllPostSitemapEntries(), getAllCategorySlugs()]);
  return [
    { url: absoluteUrl("/blog"), changeFrequency: "weekly" as const, priority: 0.8 },
    ...posts.map((post) => ({ url: absoluteUrl(`/blog/${post.slug}`), lastModified: new Date(post.modified), changeFrequency: "monthly" as const, priority: 0.7 })),
    ...categories.map((slug) => ({ url: absoluteUrl(`/blog/category/${slug}`), changeFrequency: "weekly" as const, priority: 0.6 })),
  ];
}
