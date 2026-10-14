import "./blog.css";
import { BlogFrame } from "@/components/blog/BlogFrame";

export default function BlogLayout({ children }: { children: React.ReactNode }) {
  return <BlogFrame>{children}</BlogFrame>;
}
