"use client";
import Link from "next/link";
import { Search, Globe, LayoutGrid, Bell, User } from "lucide-react";
import { useState } from "react";
import { useRouter } from "next/navigation";

export function Navbar() {
  const [query, setQuery] = useState("");
  const router = useRouter();

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) router.push(`/search?q=${encodeURIComponent(query)}`);
  };

  return (
    <header className="navbar">
      <div className="max-w-screen-2xl mx-auto h-full flex items-center gap-3 px-4">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2 shrink-0">
          <Globe className="w-7 h-7 text-geo-500" strokeWidth={2} />
          <span className="text-xl font-bold text-geo-700 tracking-tight hidden sm:block">
            GeoAtlas
          </span>
        </Link>

        {/* Nav links */}
        <nav className="hidden md:flex items-center gap-1 ml-2">
          <Link
            href="/"
            className="px-3 py-1.5 rounded-full text-sm font-semibold text-gray-900 hover:bg-gray-100 transition-colors"
          >
            Feed
          </Link>
          <Link
            href="/boards"
            className="px-3 py-1.5 rounded-full text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
          >
            Boards
          </Link>
          <Link
            href="/predictions"
            className="px-3 py-1.5 rounded-full text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
          >
            Predictions
          </Link>
          <Link
            href="/news"
            className="px-3 py-1.5 rounded-full text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
          >
            News
          </Link>
          <Link
            href="/review"
            className="px-3 py-1.5 rounded-full text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
          >
            Review
          </Link>
          <Link
            href="/map"
            className="px-3 py-1.5 rounded-full text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
          >
            Map
          </Link>
          <Link
            href="/alerts"
            className="px-3 py-1.5 rounded-full text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
          >
            Alerts
          </Link>
        </nav>

        {/* Search bar */}
        <form onSubmit={handleSearch} className="flex-1 max-w-xl mx-auto">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search events, countries, assets..."
              className="w-full pl-9 pr-4 py-2 rounded-full bg-gray-100 text-sm text-gray-900 placeholder-gray-400
                         focus:outline-none focus:ring-2 focus:ring-geo-400 focus:bg-white transition-all"
            />
          </div>
        </form>

        {/* Right icons */}
        <div className="flex items-center gap-1 shrink-0">
          <Link
            href="/alerts"
            className="p-2 rounded-full hover:bg-gray-100 transition-colors"
          >
            <Bell className="w-5 h-5 text-gray-600" />
          </Link>
          <Link
            href="/login"
            className="p-2 rounded-full hover:bg-gray-100 transition-colors"
          >
            <User className="w-5 h-5 text-gray-600" />
          </Link>
        </div>
      </div>
    </header>
  );
}
