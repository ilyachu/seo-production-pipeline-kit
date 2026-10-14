import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { BlogList } from "@/components/blog/BlogList";
import { absoluteUrl, blogConfig } from "@/config/blog";
import { getAllCategorySlugs, getCategories, getCategoryBySlug, getPostsPage } from "@/lib/wordpress";

type Props = { params: Promise<{ slug: string }>; searchParams?: Promise<{ page?: string }> };
export const dynamicParams = true;

export async function generateStaticParams() {
  return (await getAllCategorySlugs()).map((slug) => ({ slug }));
}

export async function generateMetadata({ params, searchParams }: Props): Promise<Metadata> {
  const result = await getCategoryBySlug((await params).slug);
  if (result.status === "error") throw new Error("WordPress CMS unavailable");
  const category = result.category;
  if (!category) return { title: "Категория не найдена" };
  const title = `${category.name} — ${blogConfig.blogTitle}`;
  const description = `Статьи категории «${category.name}»: практические ответы, инструкции и разборы.`;
  const page = Math.max(1, Number((await searchParams)?.page ?? "1") || 1);
  const base = `/blog/category/${category.slug}`;
  const canonical = page > 1 ? `${base}?page=${page}` : base;
  return { title, description, alternates: { canonical }, openGraph: { title, description, type: "website", url: canonical }, twitter: { card: "summary_large_image", title, description } };
}

export default async function CategoryPage({ params, searchParams }: Props) {
  const { slug } = await params;
  const page = Math.max(1, Number((await searchParams)?.page ?? "1") || 1);
  const [categories, categoryResult, postsPage] = await Promise.all([getCategories(), getCategoryBySlug(slug), getPostsPage({ categorySlug: slug, page })]);
  if (categoryResult.status === "error" || postsPage.status === "error") throw new Error("WordPress CMS unavailable");
  const category = categoryResult.category;
  if (!category) notFound();
  const description = `Статьи категории «${category.name}»: практические ответы, инструкции и разборы.`;
  const schema = { "@context": "https://schema.org", "@type": "CollectionPage", name: `${category.name} — ${blogConfig.blogTitle}`, description, url: absoluteUrl(`/blog/category/${category.slug}`), isPartOf: { "@type": "CollectionPage", name: blogConfig.blogTitle, url: absoluteUrl("/blog") } };
  return <><script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(schema).replace(/</g, "\\u003c") }} /><BlogList categories={categories} page={page} postsPage={postsPage} selectedCategory={category} /></>;
}
