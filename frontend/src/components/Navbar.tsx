"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bell, ChevronRight, Compass, Globe2, LayoutGrid, Menu, Moon, Newspaper, Search, Sparkles, Sun, UserRound, X } from "lucide-react";
import { fetchMe } from "@/lib/api";

const primary = [
  { href: "/", label: "Overview", icon: Compass },
  { href: "/map", label: "Map", icon: Globe2 },
  { href: "/news", label: "News", icon: Newspaper },
  { href: "/predictions", label: "Predictions", icon: Sparkles },
  { href: "/boards", label: "Boards", icon: LayoutGrid },
];

export function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const desktopSearchRef = useRef<HTMLInputElement>(null);
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: fetchMe, retry: false, staleTime: 300_000 });
  const isOperator = me?.role === "admin" || me?.role === "reviewer";

  useEffect(() => {
    setTheme(document.documentElement.classList.contains("dark") ? "dark" : "light");
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    document.documentElement.style.colorScheme = next;
    window.localStorage.setItem("geoatlas-theme", next);
    setTheme(next);
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.isContentEditable || (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) return;
      event.preventDefault();
      if (window.matchMedia("(max-width: 900px)").matches) setSearchOpen(true);
      else desktopSearchRef.current?.focus();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const submitSearch = (event: React.FormEvent) => {
    event.preventDefault();
    if (!query.trim()) return;
    router.push(`/search?q=${encodeURIComponent(query.trim())}`);
    setMenuOpen(false);
    setSearchOpen(false);
  };

  const navLinks = [...primary, { href: "/alerts", label: "Alerts", icon: Bell }, ...(isOperator ? [{ href: "/review", label: "Review", icon: Sparkles }] : [])];

  return (
    <>
      <header className="navbar">
        <div className="ga-navbar-inner">
          <Link href="/" className="ga-brand" aria-label="GeoAtlas home" onClick={() => setMenuOpen(false)}>
            <span className="ga-brand-mark"><Globe2 size={22} strokeWidth={1.8} /></span>
            <span>Geo<span className="ga-brand-accent">Atlas</span></span>
          </Link>

          <nav className="ga-desktop-nav" aria-label="Main navigation">
            {navLinks.map(({ href, label }) => (
              <Link key={href} href={href} className={`ga-nav-link ${pathname === href ? "is-active" : ""}`} aria-current={pathname === href ? "page" : undefined}>{label}</Link>
            ))}
          </nav>

          <form onSubmit={submitSearch} className={`ga-top-search ${searchOpen ? "is-open" : ""}`} role="search">
            <Search size={17} aria-hidden="true" />
            <input ref={desktopSearchRef} aria-label="Search GeoAtlas" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search events, places, assets..." />
            <kbd>/</kbd>
          </form>

          <div className="ga-navbar-actions">
            <button type="button" className="ga-icon-button ga-theme-toggle" aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"} title={theme === "dark" ? "Light theme" : "Dark theme"} aria-pressed={theme === "dark"} onClick={toggleTheme}>{theme === "dark" ? <Sun size={20} /> : <Moon size={20} />}</button>
            <button type="button" className="ga-icon-button ga-mobile-search-toggle" aria-label="Search" aria-expanded={searchOpen} onClick={() => setSearchOpen((open) => !open)}><Search size={20} /></button>
            <Link href="/alerts" className="ga-icon-button" aria-label="Alerts"><Bell size={19} /></Link>
            <Link href="/login" className="ga-icon-button" aria-label={me ? "Account" : "Sign in"}><UserRound size={19} /></Link>
            <button type="button" className="ga-icon-button ga-menu-toggle" aria-label={menuOpen ? "Close menu" : "Open menu"} aria-expanded={menuOpen} aria-controls="ga-mobile-menu" onClick={() => setMenuOpen((open) => !open)}>{menuOpen ? <X size={21} /> : <Menu size={21} />}</button>
          </div>
        </div>
        {searchOpen && <form onSubmit={submitSearch} className="ga-mobile-search" role="search"><Search size={18} /><input autoFocus aria-label="Search GeoAtlas" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search events, places, assets..." /><button type="submit" aria-label="Submit search"><ChevronRight size={18} /></button></form>}
      </header>

      {menuOpen && <div className="ga-menu-backdrop" onClick={() => setMenuOpen(false)} />}
      <nav id="ga-mobile-menu" className={`ga-mobile-menu ${menuOpen ? "is-open" : ""}`} aria-label="Mobile navigation" aria-hidden={!menuOpen}>
        <p className="ga-menu-heading">EXPLORE GEOATLAS</p>
        {navLinks.map(({ href, label, icon: Icon }) => <Link key={href} href={href} className={`ga-mobile-menu-link ${pathname === href ? "is-active" : ""}`} tabIndex={menuOpen ? 0 : -1} onClick={() => setMenuOpen(false)}><Icon size={20} /><span>{label}</span><ChevronRight size={16} /></Link>)}
      </nav>

      <nav className="ga-bottom-nav" aria-label="Quick navigation">
        {primary.slice(0, 4).map(({ href, label, icon: Icon }) => <Link key={href} href={href} className={pathname === href ? "is-active" : ""} aria-current={pathname === href ? "page" : undefined}><Icon size={19} /><span>{label}</span></Link>)}
        <button type="button" onClick={() => setMenuOpen(true)} aria-label="More pages"><Menu size={19} /><span>More</span></button>
      </nav>
    </>
  );
}
