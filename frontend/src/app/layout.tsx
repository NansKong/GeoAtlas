import type { Metadata } from "next";
import "./globals.css";
import "maplibre-gl/dist/maplibre-gl.css";
import { Navbar } from "@/components/Navbar";
import { Providers } from "@/components/Providers";

export const metadata: Metadata = {
  title: "GeoAtlas — Geopolitical Intelligence Platform",
  description:
    "Real-time geopolitical event intelligence mapped to financial markets and AI predictions.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body>
        <Providers>
          <Navbar />
          <main className="pt-[60px] min-h-screen">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
