import type { Metadata } from "next";
import React from 'react';
import localFont from "next/font/local";
import "./globals.css";
import { UserProvider } from '@/context/UserContext';
import DemoAccountHeader from '@/app/components/DemoAccountHeader';
import Sidebar from '@/app/components/Sidebar'; // Import the client Sidebar
import { TutorialProvider } from "@/context/TutorialContext";
import { Analytics } from "@vercel/analytics/react"
import ConditionalSidebar from "./components/ConditionalSidebar";

const geistSans = localFont({
  src: "./fonts/GeistVF.woff",
  variable: "--font-geist-sans",
  weight: "100 900",
});
const geistMono = localFont({
  src: "./fonts/GeistMonoVF.woff",
  variable: "--font-geist-mono",
  weight: "100 900",
});

export const metadata: Metadata = {
  title: "Langfour",
  description: "Learn languages with real content, tailored to your language level",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased h-dvh bg-gray-100 flex flex-col md:flex-row`}>
        <UserProvider>
          <TutorialProvider>
            <ConditionalSidebar />

            {/* The scroll container. Below md it fills what the sidebar's
                header leaves of the column; min-h-0 stops it growing to its
                content, which would make the document scroll instead. */}
            <main className="flex-1 min-h-0 overflow-y-auto h-dvh">
              <DemoAccountHeader />
              {children}
              <Analytics />
            </main>
          </TutorialProvider>
        </UserProvider>
      </body>
    </html>
  );
}