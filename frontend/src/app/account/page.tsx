"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchMe, logoutUser } from "@/lib/api";
import { LogOut, UserRound } from "lucide-react";

export default function AccountPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: user, isLoading, isError } = useQuery({ queryKey: ["me"], queryFn: fetchMe, retry: false, staleTime: 0 });

  useEffect(() => {
    if (isError) router.replace("/login");
  }, [isError, router]);

  const signOut = async () => {
    await logoutUser();
    queryClient.removeQueries({ queryKey: ["me"] });
    router.replace("/login");
  };

  return (
    <div className="ga-shell">
      <section className="ga-panel mx-auto max-w-2xl p-7 sm:p-10">
        <div className="ga-preference-icon mb-5"><UserRound size={22} /></div>
        <span className="ga-eyebrow">YOUR WORKSPACE</span>
        <h1 className="mt-2 text-3xl font-bold">Your profile</h1>
        {isLoading && <p className="mt-5 text-sm text-gray-500">Loading your account…</p>}
        {user && <>
          <p className="mt-2 text-gray-600">Signed in as {user.username}</p>
          <dl className="mt-8 grid gap-4 sm:grid-cols-2">
            <div className="rounded-xl border border-gray-200 p-4"><dt className="text-xs text-gray-500">Email</dt><dd className="mt-1 break-all font-semibold">{user.email}</dd></div>
            <div className="rounded-xl border border-gray-200 p-4"><dt className="text-xs text-gray-500">Plan</dt><dd className="mt-1 font-semibold capitalize">{user.subscription_plan}</dd></div>
          </dl>
          <button type="button" onClick={signOut} className="ga-button ga-light-button mt-8"><LogOut size={17} /> Sign out</button>
        </>}
      </section>
    </div>
  );
}
