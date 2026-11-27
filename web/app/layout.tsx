import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "ZeeNote", description: "Turn rough notes into your team's daily report." };

// Before the page draws, so it never flashes in the other colours
const THEME = `try{var t=localStorage.getItem("zeenote-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
