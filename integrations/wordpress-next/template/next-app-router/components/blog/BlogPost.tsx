import Link from "next/link";
import type { WordPressPost } from "@/lib/wordpress";
import { getPostAuthor, getPostCategories, getPostImage, getReadingTime, stripHtml } from "@/lib/wordpress";
import { BlogReadingProgress, BlogShareActions } from "./BlogTools";

export function BlogPost({ post, related }: { post: WordPressPost; related: WordPressPost[] }) {
  const title = stripHtml(post.title.rendered);
  const author = getPostAuthor(post);
  const category = getPostCategories(post)[0];
  const image = getPostImage(post);
  return <article className="seo-blog-article">
    <BlogReadingProgress />
    <nav className="seo-blog-breadcrumbs" aria-label="Хлебные крошки"><Link href="/">Главная</Link><span>→</span><Link href="/blog">Блог</Link>{category ? <><span>→</span><Link href={`/blog/category/${category.slug}`}>{category.name}</Link></> : null}</nav>
    <header className="seo-blog-article__header">
      <p className="seo-blog-meta">{new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric" }).format(new Date(post.date))} · {getReadingTime(post)}</p>
      <h1>{title}</h1>
      <p>{stripHtml(post.excerpt.rendered)}</p>
      <BlogShareActions title={title} />
    </header>
    {image ? <figure className="seo-blog-cover"><img src={image.source_url} alt={image.alt_text || title} /></figure> : null}
    <div className="seo-blog-prose" dangerouslySetInnerHTML={{ __html: post.content.rendered }} />
    {author ? <aside className="seo-blog-author"><strong>{author.name}</strong><span>Автор материала</span></aside> : null}
    {related.length ? <section className="seo-blog-related"><h2>Читайте дальше</h2><div>{related.map((item) => <Link key={item.id} href={`/blog/${item.slug}`}>{stripHtml(item.title.rendered)}</Link>)}</div></section> : null}
  </article>;
}
