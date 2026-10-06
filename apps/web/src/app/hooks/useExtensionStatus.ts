import { useEffect, useState } from 'react';

export type ExtensionStatus =
    | { state: 'checking' }
    | { state: 'missing' }
    | { state: 'installed'; version: string; signedIn: boolean; email: string | null };

/**
 * Detects the Langfour extension without needing its ID: the extension's
 * site bridge answers a window.postMessage ping. A page that was open before
 * the install has no bridge until it is reloaded, hence the slow re-ping.
 */
export function useExtensionStatus(): ExtensionStatus {
    const [status, setStatus] = useState<ExtensionStatus>({ state: 'checking' });

    useEffect(() => {
        const ping = () => window.postMessage({ source: 'langfour-web', type: 'PING' }, window.location.origin);
        const onMessage = (e: MessageEvent) => {
            if (e.source !== window || e.data?.source !== 'langfour-extension' || e.data?.type !== 'STATUS') return;
            const { version, signedIn, email } = e.data.status ?? {};
            setStatus({ state: 'installed', version: String(version ?? ''), signedIn: Boolean(signedIn), email: email ?? null });
        };
        window.addEventListener('message', onMessage);
        ping();
        const miss = setTimeout(() => setStatus((s) => (s.state === 'checking' ? { state: 'missing' } : s)), 1200);
        const poll = setInterval(ping, 3000);
        return () => {
            window.removeEventListener('message', onMessage);
            clearTimeout(miss);
            clearInterval(poll);
        };
    }, []);

    return status;
}
