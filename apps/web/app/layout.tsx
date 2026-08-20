import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ShellStateProvider } from "@/components/shell/ShellState";
import { Navbar } from "@/components/shell/Navbar";
import { StatusRail } from "@/components/shell/StatusRail";
import { MobileNav } from "@/components/shell/MobileNav";
import { Preloader } from "@/components/shell/Preloader";
import { RouteTransition } from "@/components/shell/RouteTransition";
import { DataModeBar } from "@/components/shell/DataModeBar";
import { ServiceWorkerRegister } from "@/components/shell/ServiceWorkerRegister";
import { ToastProvider } from "@/components/ui/Toast";

export const metadata: Metadata = {
  title: {
    default: "Auralis — city operations with evidence",
    template: "%s · Auralis",
  },
  description:
    "See the city. Understand the evidence. Act with authority. Auralis is an evidence-grounded operations layer for city infrastructure.",
  manifest: "/manifest.json",
  applicationName: "Auralis",
  appleWebApp: { capable: true, title: "Auralis", statusBarStyle: "default" },
  icons: { icon: "/favicon.ico" },
};

export const viewport: Viewport = {
  themeColor: "#F4F4F4",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

/**
 * Opts reveal animations in only when JS is running and motion is welcome.
 * Without it, a no-JS or reduced-motion visitor would be left with content
 * that never fades in. Inline so it runs before first paint.
 */
const MOTION_BOOT = `try{if(!matchMedia('(prefers-reduced-motion: reduce)').matches){document.documentElement.dataset.motion='on'}}catch(e){}`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <head>
        <script dangerouslySetInnerHTML={{ __html: MOTION_BOOT }} />
      </head>
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <ShellStateProvider>
          <ToastProvider>
            <Preloader />
            <Navbar />
            <StatusRail />
            <main id="main" className="appMain" tabIndex={-1}>
              <RouteTransition>{children}</RouteTransition>
            </main>
            <MobileNav />
            <DataModeBar />
            <ServiceWorkerRegister />
          </ToastProvider>
        </ShellStateProvider>
      </body>
    </html>
  );
}
