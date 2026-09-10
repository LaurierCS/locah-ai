import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LOCAH.ai",
  description:
    "An assistant over Wilfrid Laurier University's public information. Every answer cites the page it came from.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-white text-neutral-900 antialiased">{children}</body>
    </html>
  );
}
