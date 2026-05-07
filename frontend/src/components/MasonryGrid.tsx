"use client";
import Masonry from "react-masonry-css";
import { ReactNode } from "react";

const BREAKPOINTS = {
  default: 5,
  1536: 4,
  1280: 4,
  1024: 3,
  768: 2,
  640: 2,
  480: 1,
};

interface MasonryGridProps {
  children: ReactNode;
  className?: string;
}

export function MasonryGrid({ children, className }: MasonryGridProps) {
  return (
    <Masonry
      breakpointCols={BREAKPOINTS}
      className={`masonry-grid ${className ?? ""}`}
      columnClassName="masonry-col"
    >
      {children}
    </Masonry>
  );
}
