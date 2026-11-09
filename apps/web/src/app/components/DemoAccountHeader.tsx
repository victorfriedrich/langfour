"use client"

import React, { useContext } from 'react';
import Link from 'next/link';
import { UserContext } from '@/context/UserContext';
import { usePathname } from 'next/navigation';

const HIDDEN_ON = ['/get-started', '/start-learning', '/login', '/add-language', '/oauth/'];

/** One quiet line above the page while the learner is on a demo account. */
const DemoAccountHeader: React.FC = () => {
  const { user } = useContext(UserContext);
  const pathname = usePathname();

  if (!user?.is_anonymous || HIDDEN_ON.some((p) => pathname.startsWith(p))) {
    return null;
  }

  return (
    <div className="hidden md:flex h-11 items-center gap-2.5 border-b border-[#ECEDF0] bg-white px-4 sm:px-8 text-sm text-[#5C606B]">
      <span className="h-[7px] w-[7px] flex-none rounded-full bg-[#F5A524]" aria-hidden="true" />
      You’re using a demo account, so your words aren’t saved yet.
      <Link href="/start-learning" className="font-semibold text-[#222326] hover:underline underline-offset-[3px]">
        Save progress
      </Link>
      <Link href="/login" className="ml-auto font-medium text-[#5C606B] hover:text-[#222326]">
        Log in
      </Link>
    </div>
  );
};

export default DemoAccountHeader;
