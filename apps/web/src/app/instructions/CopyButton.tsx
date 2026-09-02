'use client';

export default function CopyButton() {
  return (
    <button 
      onClick={() => navigator.clipboard.writeText('chrome://extensions')}
      className="text-sm text-indigo-600 hover:text-indigo-700 font-medium"
    >
      Copy URL
    </button>
  );
}
