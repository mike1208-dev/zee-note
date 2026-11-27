import { Shell } from "@/components/Shell";
import { SessionProvider } from "@/lib/session";

export default function SignedInLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <Shell>{children}</Shell>
    </SessionProvider>
  );
}
