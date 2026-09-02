import { sendToBackground } from './messages';

// Send words to background for storage
type StorageResponse = { success: boolean; error?: string };
type StoredWordsResponse = { words: string[] };

export function storeWords(words: string[], language: string): Promise<StorageResponse> {
    return new Promise((resolve, reject) => {
        console.log(`Sending ${words.length} ${language} words to background for storage`);

        const wordsArray = Array.from(words);
        sendToBackground<StorageResponse>(
            { type: 'STORE_WORDS', words: wordsArray, language },
            (response) => {
                if (chrome.runtime.lastError) {
                    console.error('Error in storage message:', chrome.runtime.lastError);
                    reject(chrome.runtime.lastError);
                    return;
                }

                if (response && response.success) {
                    console.log('Words successfully stored in background');
                    resolve(response);
                } else {
                    console.error('Failed to store words:', response?.error || 'Unknown error');
                    reject(new Error(response?.error || 'Unknown error'));
                }
            }
        );
    });
}

// Get words from background storage
export function getStoredWords(language: string): Promise<Set<string>> {
    return new Promise((resolve, reject) => {
        console.log(`Requesting ${language} words from background storage`);

        sendToBackground<StoredWordsResponse>(
            { type: 'GET_WORDS', language },
            (response) => {
                if (chrome.runtime.lastError) {
                    console.error('Error in retrieval message:', chrome.runtime.lastError);
                    reject(chrome.runtime.lastError);
                    return;
                }

                console.log(`Received ${response.words.length} words from background`);
                resolve(new Set(response.words));
            }
        );
    });
}
