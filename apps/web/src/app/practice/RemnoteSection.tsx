'use client';

import { Layers } from 'lucide-react';

/** The invitation to review in RemNote instead. Connecting starts in RemNote
 *  (the plugin's "Langfour: Connect"), which opens Langfour to approve; once
 *  connected, the page's scheduler label holds the connection instead. */
export default function RemnoteSection() {
  return (
    <section className="flex gap-3 text-sm">
      <Layers size={18} className="mt-0.5 shrink-0 text-indigo-500" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-gray-900">Already use RemNote?</p>
        <p className="mt-0.5 text-gray-600">
          Review your Langfour words there instead. Install the Langfour plugin in RemNote, run{' '}
          <span className="font-medium text-gray-800">Langfour: Connect</span> and approve the code it shows. Flashcards you
          already have are reused.
        </p>
      </div>
    </section>
  );
}
