import type { Metadata } from "next";
import "./globals.css";
import HealthCheck from "./components/HealthCheck";

export const metadata: Metadata = {
  title: "LOCAH.ai",
  description:
    "An assistant over Wilfrid Laurier University's public information. Every answer cites the page it came from.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-white text-neutral-900 antialiased">
        <header className="border-b border-neutral-200 bg-neutral-50 px-6 py-3">
          <div className="mx-auto max-w-7xl flex items-center justify-between">
            <h1 className="font-semibold">LOCAH.ai</h1>
            <HealthCheck />
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
