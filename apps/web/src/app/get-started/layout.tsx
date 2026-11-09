import React from 'react';
import { UserProvider } from '@/context/UserContext';
import { TutorialProvider } from '@/context/TutorialContext';
import { Analytics } from '@vercel/analytics/react';

export default function GetStartedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-white">
      <UserProvider>
        <TutorialProvider>
          {children}
          <Analytics />
        </TutorialProvider>
      </UserProvider>
    </div>
  );
}
