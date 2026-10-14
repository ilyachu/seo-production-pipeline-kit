import type { Metadata } from "next";
import { BlogList } from "@/components/blog/BlogList";
import { absoluteUrl, blogConfig } from "@/config/blog";
import { getCategories, getPostsPage } from "@/lib/wordpress";

export async function generateMetadata({ searchParams }: { searchParams?: Promise<{ page?: string }> }): Promise<Metadata> {
  const page = Math.max(1, Number((await searchParams)?.page ?? "1") || 1);
  const canonical = page > 1 ? `/blog?page=${page}` : "/blog";
  return {
    title: blogConfig.blogTitle,
    description: blogConfig.blogDescription,
    alternates: { canonical },
    openGraph: { title: blogConfig.blogTitle, description: blogConfig.blogDescription, url: canonical, type: "website" },
    twitter: { card: "summary_large_image", title: blogConfig.blogTitle, description: blogConfig.blogDescription },
  };
}

export default async function BlogPage({ searchParams }: { searchParams?: Promise<{ page?: string }> }) {
  const query = (await searchParams) ?? {};
  const page = Math.max(1, Number(query.page ?? "1") || 1);
  const [categories, postsPage] = await Promise.all([getCategories(), getPostsPage({ page })]);
  const schema = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: blogConfig.blogTitle,
    description: blogConfig.blogDescription,
    url: absoluteUrl("/blog"),
    isPartOf: { "@type": "WebSite", name: blogConfig.siteName, url: absoluteUrl("/") },
  };
  return <><script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(schema).replace(/</g, "\\u003c") }} /><BlogList categories={categories} page={page} postsPage={postsPage} /></>;
}
