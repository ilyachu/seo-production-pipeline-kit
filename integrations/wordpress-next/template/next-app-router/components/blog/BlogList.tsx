import Link from "next/link";
import type { PostsPage, WordPressTerm } from "@/lib/wordpress";
import { getPostCategories, getPostImage, getReadingTime, stripHtml } from "@/lib/wordpress";

export function BlogList({ categories, page, postsPage, selectedCategory }: { categories: WordPressTerm[]; page: number; postsPage: PostsPage; selectedCategory?: WordPressTerm | null }) {
  const hrefForPage = (value: number) => {
    const base = selectedCategory ? `/blog/category/${selectedCategory.slug}` : "/blog";
    return value <= 1 ? base : `${base}?page=${value}`;
  };
  return <>
    <header className="seo-blog-hero">
      <p className="seo-blog-eyebrow">Материалы</p>
      <h1>{selectedCategory ? selectedCategory.name : "Блог"}</h1>
      <p>Полезные ответы, инструкции и разборы по темам, которые важны читателям.</p>
      <nav className="seo-blog-categories" aria-label="Категории блога">
        <Link href="/blog" aria-current={!selectedCategory ? "page" : undefined}>Все статьи</Link>
        {categories.map((category) => <Link key={category.id} href={`/blog/category/${category.slug}`} aria-current={selectedCategory?.slug === category.slug ? "page" : undefined}>{category.name}</Link>)}
      </nav>
    </header>
    <section className="seo-blog-container" aria-live="polite">
      {postsPage.status !== "ready" ? <div className="seo-blog-empty"><h2>{postsPage.status === "missing-config" ? "Блог подключается" : "Контент временно недоступен"}</h2><p>Проверьте WordPress endpoint и повторите загрузку.</p></div> : null}
      {postsPage.status === "ready" && postsPage.posts.length === 0 ? <div className="seo-blog-empty"><h2>Статей пока нет</h2><p>В этой категории ещё не опубликованы материалы.</p></div> : null}
      <div className="seo-blog-grid">
        {postsPage.posts.map((post) => {
          const image = getPostImage(post);
          const category = getPostCategories(post)[0];
          return <article className="seo-blog-card" key={post.id}>
            <Link className="seo-blog-card__image" href={`/blog/${post.slug}`} aria-label={stripHtml(post.title.rendered)}>{image ? <img src={image.source_url} alt={image.alt_text || stripHtml(post.title.rendered)} loading="lazy" /> : <span aria-hidden="true" />}</Link>
            <div className="seo-blog-card__body">
              <p className="seo-blog-meta">{category?.name ?? "Статья"} · {getReadingTime(post)}</p>
              <h2><Link href={`/blog/${post.slug}`}>{stripHtml(post.title.rendered)}</Link></h2>
              <p>{stripHtml(post.excerpt.rendered)}</p>
            </div>
          </article>;
        })}
      </div>
      {postsPage.totalPages > 1 ? <nav className="seo-blog-pagination" aria-label="Пагинация">
        {page > 1 ? <Link href={hrefForPage(page - 1)}>Назад</Link> : <span />}
        <span>Страница {page} из {postsPage.totalPages}</span>
        {page < postsPage.totalPages ? <Link href={hrefForPage(page + 1)}>Дальше</Link> : <span />}
      </nav> : null}
    </section>
  </>;
}
