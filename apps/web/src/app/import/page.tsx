'use client';

import { useState } from 'react';
import { useFlashcardsUpload } from '../hooks/useFlashcards';
import VocabularyImporter from '../components/FlashcardImporter';
import FlashcardImport from '../components/FlashcardImport';
import { useRouter } from 'next/navigation';

export default function ImportPage() {
  const [uploadResponse, setUploadResponse] = useState(null);
  const { uploadFlashcards, loading, error } = useFlashcardsUpload();
  const router = useRouter();
  
  // Handle file upload completion
  const handleUploadComplete = (data: unknown) => {
    console.log('Upload complete:', data);
    setUploadResponse(data);
  };
  
  // Handle going back from the confirmation screen
  const handleImportCancel = () => {
    setUploadResponse(null);
  };
  
  // Send the user to the collection that received the imported flashcards.
  const handleImportComplete = (selectedWords: number[], status: 'learning' | 'known') => {
    console.log('Imported words:', selectedWords, status);
    router.push(status === 'known' ? '/progress' : '/vocabulary');
  };
  
  // Determine which view to show
  const showConfirmation = uploadResponse !== null;
  
  return (
    <div className="min-h-screen">
      {showConfirmation ? (
        // Show the confirmation screen if we have upload data
        <FlashcardImport 
          data={uploadResponse}
          onCancel={handleImportCancel}
          onComplete={handleImportComplete}
        />
      ) : (
        // Show the importer if we don't have data yet
        <VocabularyImporter 
          onBack={() => router.push('/progress')}
          onComplete={handleUploadComplete}
        />
      )}
    </div>
  );
}
