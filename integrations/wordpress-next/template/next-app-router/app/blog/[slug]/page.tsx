import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { BlogPost } from "@/components/blog/BlogPost";
import { absoluteUrl, blogConfig } from "@/config/blog";
import { getAllPostSlugs, getPostBySlug, getPostImage, getRelatedPosts, getSeoDescription, getSeoTitle } from "@/lib/wordpress";

type Props = { params: Promise<{ slug: string }> };
export const dynamicParams = true;

export async function generateStaticParams() {
  return (await getAllPostSlugs()).map((slug) => ({ slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const result = await getPostBySlug((await params).slug);
  if (result.status === "error") throw new Error("WordPress CMS unavailable");
  const post = result.post;
  if (!post) return { title: "Статья не найдена" };
  const title = getSeoTitle(post);
  const description = getSeoDescription(post);
  const image = getPostImage(post);
  const canonical = `/blog/${post.slug}`;
  return {
    title,
    description,
    alternates: { canonical },
    openGraph: { title: post.yoast_head_json?.og_title || title, description: post.yoast_head_json?.og_description || description, type: "article", url: canonical, publishedTime: post.date, modifiedTime: post.modified, images: image ? [{ url: image.source_url, alt: image.alt_text }] : undefined },
    twitter: { card: "summary_large_image", title, description, images: image ? [image.source_url] : undefined },
  };
}

export default async function ArticlePage({ params }: Props) {
  const result = await getPostBySlug((await params).slug);
  if (result.status === "error") throw new Error("WordPress CMS unavailable");
  const post = result.post;
  if (!post) notFound();
  const [related, image] = await Promise.all([getRelatedPosts(post), Promise.resolve(getPostImage(post))]);
  const schema = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: getSeoTitle(post),
    description: getSeoDescription(post),
    datePublished: post.date,
    dateModified: post.modified,
    author: { "@type": "Person", name: blogConfig.authorName, url: absoluteUrl(blogConfig.authorUrl) },
    mainEntityOfPage: { "@type": "WebPage", "@id": absoluteUrl(`/blog/${post.slug}`) },
    image: image ? [image.source_url] : undefined,
  };
  return <><script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(schema).replace(/</g, "\\u003c") }} /><BlogPost post={post} related={related} /></>;
}
