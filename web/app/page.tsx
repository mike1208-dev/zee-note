"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { getToken } from "@/lib/api";

// The start: signed-in people go to their first page (the menu sends each role to the right one)
export default function Start() {
  const router = useRouter();
  useEffect(() => router.replace(getToken() ? "/write" : "/login"), [router]);
  return <div className="center soft">Loading…</div>;
}
