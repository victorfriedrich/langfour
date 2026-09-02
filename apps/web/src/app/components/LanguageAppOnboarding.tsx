'use client';

import React, { useState, useEffect, useContext } from 'react';
import { UserContext } from '@/context/UserContext';
import { LANGUAGE_LIST, LANGUAGES, LanguageCode } from '@/lib/languages';
import { useRouter, useSearchParams } from 'next/navigation';
import levelsData from '../levels.json';
import { useCreateDemoAccount } from '../hooks/useCreateDemoAccount';

interface LanguageLevel {
  level: string;
  description: string;
  words: number[];
}

interface LanguageOption {
  code: LanguageCode;
  name: string;
  disabled: boolean;
}

interface LanguageAppOnboardingProps {
  onComplete?: () => void;
  isNewAccount?: boolean;
  defaultLanguageCode?: string;
}

const LanguageAppOnboarding: React.FC<LanguageAppOnboardingProps> = ({
  onComplete,
  isNewAccount = false,
  defaultLanguageCode
}) => {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { user, initializeLanguage, setLanguage } = useContext(UserContext);
  const { createDemoAccount, isLoading: isCreatingDemoAccount } = useCreateDemoAccount();

  const [currentStep, setCurrentStep] = useState(1);
  const totalSteps = 2;
  const [selectedLanguage, setSelectedLanguage] = useState<LanguageOption | null>(null);
  const [selectedLevel, setSelectedLevel] = useState<LanguageLevel | null>(null);
  const [isInitializing, setIsInitializing] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  
  const levels: LanguageLevel[] = levelsData as LanguageLevel[];

  // Derived from LANGUAGE_LIST, so this screen cannot drift from the canonical
  // set the way it had: it offered a disabled Italian while LanguageSetup
  // offered an enabled one, and both listed a Russian that initialize_account
  // now rejects with a raw Postgres exception. Only the disabled overlay is
  // per-screen -- onboarding still ships Spanish first.
  const languages: LanguageOption[] = LANGUAGE_LIST.map((lang) => ({
    code: lang.code,
    name: lang.name,
    disabled: lang.code !== 'es',
  }));


  // Initialize from URL param or prop
  useEffect(() => {
    const langCode = defaultLanguageCode || searchParams.get('language');
    if (langCode) {
      const matchedLanguage = languages.find(
        lang => lang.code === langCode && !lang.disabled
      );
      if (matchedLanguage) {
        setSelectedLanguage(matchedLanguage);
        setCurrentStep(2); // Skip to level selection
      }
    }
  }, [searchParams, defaultLanguageCode]);

  const handleNext = () => setCurrentStep(currentStep + 1);
  const handleBack = () => setCurrentStep(currentStep - 1);


  const handleLanguageSelect = (language: LanguageOption) => {
    if (!language.disabled) {
      setSelectedLanguage(language);
    }
  };

  const handleLevelSelect = (level: LanguageLevel) => {
    setSelectedLevel(level);
  };

  const handleInitializeLanguage = async (level: LanguageLevel) => {
    if (selectedLanguage && level) {
      setIsInitializing(true);
      try {
        // Create the demo account if no non-anonymous user exists
        if (!user || user.is_anonymous) {
          await createDemoAccount({
            language: selectedLanguage.code,
            level: level.level,
          });
        }
        // Initialize the language for the account
        await initializeLanguage(selectedLanguage.code, level.level);
        // Update the context with the new language
        setLanguage(LANGUAGES[selectedLanguage.code]);
        setIsComplete(true);
        // After a brief delay, call onComplete or redirect
        if (onComplete) {
            onComplete();
          } else {
            router.push('/videos');
          }
      } catch (error) {
        console.error('Error initializing language:', error);
        alert('An error occurred while setting up the language. Please try again.');
        setIsInitializing(false);
      }
    }
  };

  const LanguageSelection = () => (
    <div className="h-full flex flex-col">
      <div className="flex-1 p-6">
        <h2 className="text-2xl font-bold mb-6">Select your language</h2>
        {languages.filter(lang => !lang.disabled).map(language => (
          <button
            key={language.code}
            onClick={() => {
              handleLanguageSelect(language);
              handleNext();
            }}
            className="flex items-center p-4 w-full border border-gray-200 rounded-lg shadow-sm mb-3 hover:bg-gray-50"
          >
            <div className="w-8 h-6 mr-4 overflow-hidden rounded-md">
              <img 
                src={`https://flagcdn.com/w80/${language.code}.png`} 
                alt={`${language.name} flag`}
                className="w-full h-full object-cover"
              />
            </div>
            <span className="text-lg">{language.name}</span>
            <span className="ml-auto text-gray-400">›</span>
          </button>
        ))}
        {/* Disabled languages */}
        {languages.filter(lang => lang.disabled).map(language => (
          <button
            key={language.code}
            disabled
            className="flex items-center p-4 w-full border border-gray-200 rounded-lg shadow-sm mb-3 opacity-50 cursor-not-allowed"
          >
            <div className="w-8 h-6 mr-4 overflow-hidden rounded-md">
              <img 
                src={`https://flagcdn.com/w80/${language.code}.png`} 
                alt={`${language.name} flag`}
                className="w-full h-full object-cover"
              />
            </div>
            <span className="text-lg">{language.name}</span>
            <span className="ml-auto text-gray-400">Coming soon</span>
          </button>
        ))}
      </div>
    </div>
  );

  const KnowledgeLevel = () => (
    <div className="h-full flex flex-col">
      <div className="p-6 flex-1">
        <button onClick={handleBack} className="mb-2 text-gray-500">
          ← Back
        </button>
        <h2 className="text-2xl font-bold mb-4">
          How good is your {selectedLanguage?.name}?
        </h2>
        <p className="text-gray-600 mb-6">
          Based on your selection, we'll customize your experience and add the most common words. You can always adjust this later.
        </p>
        <div className="space-y-3">
          {levels.map(level => (
            <button
              key={level.level}
              onClick={async () => {
                handleLevelSelect(level);
                await handleInitializeLanguage(level);
              }}
              className="w-full text-left p-4 border border-gray-200 rounded-xl shadow-sm hover:border-gray-300"
            >
              <span className="font-bold">{level.level}</span>
              <p className="text-gray-600 text-sm">{level.description}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  );


  const SuccessScreen = () => (
    <div className="h-full flex flex-col items-center justify-center p-6">
      <div className="text-center">
        <div className="mb-4 text-green-500">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-16 w-16 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h2 className="text-2xl font-bold mb-2">
          {selectedLanguage?.name} successfully set up!
        </h2>
        <p className="text-gray-500">
          Redirecting to content...
        </p>
      </div>
    </div>
  );

  // Render the current step
  const renderStep = () => {
    if (isComplete) {
      return <SuccessScreen />;
    }
    switch (currentStep) {
      case 1:
        return <LanguageSelection />;
      case 2:
        return <KnowledgeLevel />;
      default:
        return <LanguageSelection />;
    }
  };

  return (
    <div className="min-h-screen bg-gray-100 flex items-center justify-center relative overflow-hidden">
      <div className="flex flex-grow max-w-xl w-full z-10">
        {/* Onboarding interface */}
        <div className="w-full bg-white flex flex-col min-h-screen shadow-lg">
          {currentStep > 1 && currentStep <= totalSteps && !isComplete && (
            <div className="w-full h-1 bg-gray-100">
              <div
                className="h-full bg-indigo-500 transition-all duration-300"
                style={{ width: `${((currentStep - 1) / (totalSteps - 1)) * 100}%` }}
              />
            </div>
          )}
          <div className="flex-1 overflow-y-auto">
            {renderStep()}
          </div>
        </div>
      </div>
  
      {/* Overlay footer */}
      {(currentStep === 1 || currentStep === 2) && !isComplete && (
        <div className="absolute bottom-4 text-sm text-gray-600 z-20">
          Already have an account?{' '}
          <a href="/login" className="text-indigo-500 font-semibold hover:underline">
            Sign in
          </a>
        </div>
      )}
    </div>
  );
  

};

export default LanguageAppOnboarding;
