"use client";
import Link from "next/link";
import { LayoutGrid, Lock, Globe } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { Board } from "@/lib/api";

interface BoardCardProps {
  board: Board;
}

export function BoardCard({ board }: BoardCardProps) {
  const timeAgo = formatDistanceToNow(new Date(board.created_at), { addSuffix: true });

  return (
    <Link href={`/boards/${board.id}`} className="block pin-card group">
      {/* Cover / placeholder */}
      <div className="h-36 bg-gradient-to-br from-geo-100 to-geo-200 flex items-center justify-center">
        <LayoutGrid className="w-10 h-10 text-geo-400 opacity-60" />
      </div>

      <div className="p-3">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-sm font-semibold text-gray-900 line-clamp-2 leading-snug">
            {board.title}
          </h3>
          {board.visibility === "private" ? (
            <Lock className="w-3.5 h-3.5 text-gray-400 shrink-0 mt-0.5" />
          ) : (
            <Globe className="w-3.5 h-3.5 text-gray-400 shrink-0 mt-0.5" />
          )}
        </div>
        {board.description && (
          <p className="text-xs text-gray-400 mt-1 line-clamp-2">{board.description}</p>
        )}
        <div className="flex items-center justify-between mt-2">
          <span className="text-xs text-gray-400">{board.pin_count} pins</span>
          <span className="text-xs text-gray-400">{timeAgo}</span>
        </div>
      </div>
    </Link>
  );
}
