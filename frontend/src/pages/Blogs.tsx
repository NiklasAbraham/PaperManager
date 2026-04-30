import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  listBlogs,
  registerBlog,
  deleteBlog,
  fetchBlogPosts,
  listBlogPosts,
  getRandomBlogPost,
} from "../api/client";
import type { Blog, BlogPost } from "../types";

const STATUS_COLORS: Record<string, string> = {
  unread:  "bg-blue-100 text-blue-700",
  reading: "bg-amber-100 text-amber-700",
  read:    "bg-green-100 text-green-700",
};

const PARSER_LABELS: Record<string, string> = {
  substack:  "Substack",
  wordpress: "WordPress",
  jekyll:    "Jekyll",
  generic:   "RSS",
};

export default function Blogs() {
  const navigate = useNavigate();
  const [blogs, setBlogs]           = useState<Blog[]>([]);
  const [selected, setSelected]     = useState<Blog | null>(null);
  const [posts, setPosts]           = useState<BlogPost[]>([]);
  const [loading, setLoading]       = useState(false);
  const [postsLoading, setPostsLoading] = useState(false);
  const [fetching, setFetching]     = useState(false);
  const [addUrl, setAddUrl]         = useState("");
  const [adding, setAdding]         = useState(false);
  const [addError, setAddError]     = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const loadBlogs = () => {
    setLoading(true);
    listBlogs()
      .then(setBlogs)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadBlogs(); }, []);

  const selectBlog = (blog: Blog) => {
    setSelected(blog);
    setPostsLoading(true);
    listBlogPosts(blog.id)
      .then(setPosts)
      .catch(() => {})
      .finally(() => setPostsLoading(false));
  };

  const handleAdd = async () => {
    const url = addUrl.trim();
    if (!url) return;
    setAdding(true);
    setAddError("");
    try {
      const blog = await registerBlog(url);
      setAddUrl("");
      loadBlogs();
      selectBlog(blog);
    } catch (e: unknown) {
      setAddError(e instanceof Error ? e.message : "Failed to register blog");
    } finally {
      setAdding(false);
    }
  };

  const handleFetch = async () => {
    if (!selected) return;
    setFetching(true);
    try {
      const result = await fetchBlogPosts(selected.id);
      await listBlogPosts(selected.id).then(setPosts);
      loadBlogs();
      alert(`Fetched ${result.total_fetched} posts, ${result.new_posts} new.`);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Fetch failed");
    } finally {
      setFetching(false);
    }
  };

  const handleDelete = async (blogId: string) => {
    await deleteBlog(blogId);
    setConfirmDelete(null);
    if (selected?.id === blogId) {
      setSelected(null);
      setPosts([]);
    }
    loadBlogs();
  };

  const handleSurprise = async () => {
    try {
      const post = await getRandomBlogPost("unread");
      navigate(`/blogs/posts/${post.id}`);
    } catch {
      try {
        const post = await getRandomBlogPost("any");
        navigate(`/blogs/posts/${post.id}`);
      } catch {
        alert("No blog posts found. Register a blog and fetch posts first.");
      }
    }
  };

  const unreadCount = posts.filter(p => p.reading_status === "unread").length;
  const readCount   = posts.filter(p => p.reading_status === "read").length;

  return (
    <div className="flex h-full min-h-0">
      {/* Left sidebar — blog list */}
      <aside className="w-72 border-r border-gray-200 bg-white flex flex-col">
        <div className="p-4 border-b border-gray-100">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-gray-900">Blogs</h2>
            <button
              onClick={handleSurprise}
              className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded bg-violet-600 text-white hover:bg-violet-700 transition-colors"
              title="Open a random unread post"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
                <path d="M10 3.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM2 10a8 8 0 1 1 16 0 8 8 0 0 1-16 0Z" />
                <path d="M10 8a1 1 0 0 1 1 1v2a1 1 0 1 1-2 0V9a1 1 0 0 1 1-1ZM10 14a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" />
              </svg>
              Surprise me
            </button>
          </div>

          {/* Add blog form */}
          <div className="flex gap-1.5">
            <input
              value={addUrl}
              onChange={e => setAddUrl(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleAdd()}
              placeholder="https://blog.example.com"
              className="flex-1 text-xs border border-gray-300 rounded px-2 py-1.5 focus:outline-none focus:border-violet-400"
            />
            <button
              onClick={handleAdd}
              disabled={adding || !addUrl.trim()}
              className="px-2.5 py-1.5 text-xs font-medium rounded bg-gray-900 text-white hover:bg-gray-700 disabled:opacity-40 transition-colors"
            >
              {adding ? "…" : "Add"}
            </button>
          </div>
          {addError && <p className="text-xs text-red-500 mt-1">{addError}</p>}
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading && <p className="text-xs text-gray-400 p-4">Loading…</p>}
          {blogs.map(blog => (
            <div
              key={blog.id}
              onClick={() => selectBlog(blog)}
              className={`px-4 py-3 cursor-pointer border-b border-gray-100 hover:bg-gray-50 transition-colors ${
                selected?.id === blog.id ? "bg-violet-50 border-l-2 border-l-violet-500" : ""
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-900 truncate">{blog.name}</p>
                  <p className="text-xs text-gray-400 truncate">{blog.url.replace(/^https?:\/\//, "")}</p>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  <span className="text-xs text-gray-400">{blog.post_count} posts</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">
                    {PARSER_LABELS[blog.parser] ?? blog.parser}
                  </span>
                </div>
              </div>
            </div>
          ))}
          {!loading && blogs.length === 0 && (
            <p className="text-xs text-gray-400 p-4">No blogs yet. Add one above.</p>
          )}
        </div>
      </aside>

      {/* Main content — post list */}
      <main className="flex-1 flex flex-col min-w-0 bg-gray-50">
        {selected ? (
          <>
            {/* Blog header */}
            <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
              <div className="flex-1 min-w-0">
                <h1 className="text-lg font-semibold text-gray-900">{selected.name}</h1>
                {selected.description && (
                  <p className="text-sm text-gray-500 mt-0.5">{selected.description}</p>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-xs text-gray-400">{unreadCount} unread · {readCount} read</span>
                <button
                  onClick={handleFetch}
                  disabled={fetching}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded border border-gray-300 hover:bg-gray-50 disabled:opacity-40 transition-colors"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className={`w-3.5 h-3.5 ${fetching ? "animate-spin" : ""}`}>
                    <path fillRule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clipRule="evenodd" />
                  </svg>
                  {fetching ? "Fetching…" : "Fetch new posts"}
                </button>
                <button
                  onClick={() => setConfirmDelete(selected.id)}
                  className="p-1.5 text-gray-400 hover:text-red-500 rounded hover:bg-red-50 transition-colors"
                  title="Delete blog"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                    <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clipRule="evenodd" />
                  </svg>
                </button>
              </div>
            </div>

            {/* Post list */}
            <div className="flex-1 overflow-y-auto p-4">
              {postsLoading && <p className="text-sm text-gray-400">Loading posts…</p>}
              {!postsLoading && posts.length === 0 && (
                <p className="text-sm text-gray-400">No posts yet. Click "Fetch new posts" to load them.</p>
              )}
              <div className="space-y-2">
                {posts.map(post => (
                  <PostRow key={post.id} post={post} onClick={() => navigate(`/blogs/posts/${post.id}`)} />
                ))}
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-400">
            <div className="text-center">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1} stroke="currentColor" className="w-12 h-12 mx-auto mb-3 opacity-30">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 0 1-2.25 2.25M16.5 7.5V18a2.25 2.25 0 0 0 2.25 2.25M16.5 7.5V4.875c0-.621-.504-1.125-1.125-1.125H4.125C3.504 3.75 3 4.254 3 4.875V18a2.25 2.25 0 0 0 2.25 2.25h13.5M6 7.5h3v3H6v-3Z" />
              </svg>
              <p className="text-sm">Select a blog to see its posts</p>
              <p className="text-xs mt-1">or hit <strong>Surprise me</strong> for a random unread post</p>
            </div>
          </div>
        )}
      </main>

      {/* Delete confirmation */}
      {confirmDelete && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl p-6 w-80">
            <h3 className="font-semibold text-gray-900 mb-2">Delete blog?</h3>
            <p className="text-sm text-gray-500 mb-4">This will also delete all fetched posts. This cannot be undone.</p>
            <div className="flex gap-2 justify-end">
              <button onClick={() => setConfirmDelete(null)} className="px-3 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-50">Cancel</button>
              <button onClick={() => handleDelete(confirmDelete)} className="px-3 py-1.5 text-sm rounded bg-red-600 text-white hover:bg-red-700">Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function PostRow({ post, onClick }: { post: BlogPost; onClick: () => void }) {
  const date = post.published_at ? new Date(post.published_at).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : "";

  return (
    <div
      onClick={onClick}
      className="bg-white rounded-lg border border-gray-200 px-4 py-3 cursor-pointer hover:border-violet-300 hover:shadow-sm transition-all"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className={`text-sm font-medium leading-snug ${post.reading_status === "read" ? "text-gray-400" : "text-gray-900"}`}>
            {post.title}
          </p>
          {post.description && (
            <p className="text-xs text-gray-400 mt-0.5 line-clamp-2">{post.description}</p>
          )}
          <div className="flex items-center gap-2 mt-1.5">
            {post.author && <span className="text-xs text-gray-400">{post.author}</span>}
            {date && <span className="text-xs text-gray-300">{date}</span>}
            {post.summary && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-violet-50 text-violet-600">summarized</span>
            )}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1.5 shrink-0">
          <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${STATUS_COLORS[post.reading_status]}`}>
            {post.reading_status}
          </span>
          {!post.imported && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-400">not imported</span>
          )}
        </div>
      </div>
    </div>
  );
}
